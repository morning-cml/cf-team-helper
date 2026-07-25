# -*- coding: utf-8 -*-
"""Flask 路由：主页查询 + 刷题器 + 组队作战 + 大部队增删刷 + 心跳。"""
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from flask import jsonify, render_template, request

from . import analysis, army, cf_api, config, contests, todo


def _parallel_map(fn, items):
    """对 items 并行执行 fn 并保序返回；并发受 cf_api 全局信号量限流。"""
    if not items:
        return []
    workers = min(len(items), config.HTTP_MAX_CONCURRENCY)
    with ThreadPoolExecutor(max_workers=workers) as ex:
        return list(ex.map(fn, items))

# ==================== 心跳：页面关闭后自动退出进程 ====================
_last_heartbeat = time.time()


def _touch():
    global _last_heartbeat
    _last_heartbeat = time.time()


def _request_shutdown():
    """主动请求退出：把心跳推到"再过 SHUTDOWN_GRACE 秒就判超时"。

    不能直接置 0——顶栏跳转这类应用内导航同样会触发 pagehide 发信标，而新页面的
    第一次心跳要等它加载完才到；置 0 会让看门狗在这个空档里立刻判超时、把进程杀在
    跳转途中。留一小段宽限期后，新页面（或其它标签页）的任意一次 _touch() 都能取消。"""
    global _last_heartbeat
    _last_heartbeat = time.time() - config.HEARTBEAT_TIMEOUT + config.SHUTDOWN_GRACE


def start_heartbeat_watcher():
    def watch():
        while True:
            time.sleep(2)
            if time.time() - _last_heartbeat > config.HEARTBEAT_TIMEOUT:
                print("💀 页面已关闭，进程自动退出")
                os._exit(0)
    threading.Thread(target=watch, daemon=True).start()


# ==================== 单个用户的完整分析 ====================
def _analyze_handle(handle, contest_type):
    # 整体 try：任何一人分析异常都只算"查询失败"，不连累并行里的其他人 / 整页 500
    try:
        info, subs, rating_hist = cf_api.fetch_user_bundle(handle)   # 3 个接口并行拉取
        if not info or subs is None:
            return None

        prob   = analysis.analyze_problems(subs)
        recent = analysis.analyze_recent_tags(subs)
        wall   = analysis.analyze_weakness_wall(subs)
        plan   = analysis.generate_training_plan(info["rating"], recent)

        imp = plan["zones"]["improve"]      # 区间下界已由 generate_training_plan 顶在题库最低分
        recos = analysis.recommend_problems(
            imp["min"], imp["max"], plan["weak_tags"], prob["solved_keys"])
        prob.pop("solved_keys", None)      # set 不进模板

        return {
            **info, **prob,
            "rank_info":      analysis.get_rank_info(info["rating"]),
            "prediction":     analysis.generate_prediction(info["rating"], contest_type),
            "recent_tags":    recent,
            "weakness_wall":  wall,
            "activity":       analysis.activity_heatmap(subs),
            "training_plan":  plan,
            "recommend":      recos,
            "contests":       analysis.recent_contests(rating_hist, 5),
            "rating_history": rating_hist,
        }
    except Exception as e:
        print(f"⚠️ 分析 {handle} 失败：{e}")
        return None


# ==================== 组队作战：单个成员的轻量分析（只取分工矩阵所需） ====================
def _fetch_member(handle):
    try:
        info, subs, _ = cf_api.fetch_user_bundle(handle)
        if not info or subs is None:
            return None
        prob = analysis.analyze_problems(subs)
        return {
            "handle":      info["handle"],
            "rating":      info["rating"],
            "rank_info":   analysis.get_rank_info(info["rating"]),
            "tag_counts":  dict(prob["tags"]),
            "solved_keys": prob["solved_keys"],
        }
    except Exception as e:
        print(f"⚠️ 分析队员 {handle} 失败：{e}")
        return None


# ==================== head-to-head 对比：单人取对比所需的全量字段 ====================
def _fetch_compare(handle):
    try:
        info, subs, rating_hist = cf_api.fetch_user_bundle(handle)
        if not info or subs is None:
            return None
        prob = analysis.analyze_problems(subs)
        return {
            "handle":         info["handle"],
            "rating":         info["rating"],
            "max_rating":     info["max_rating"],
            "medal_class":    info["medal_class"],
            "rank_info":      analysis.get_rank_info(info["rating"]),
            "ac":             prob["ac"],
            "submit":         prob["submit"],
            "rate":           prob["rate"],
            "histogram":      prob["histogram"],
            "tags":           prob["tags"],
            "solved_keys":    prob["solved_keys"],
            "rating_history": rating_hist,
        }
    except Exception as e:
        print(f"⚠️ 对比拉取 {handle} 失败：{e}")
        return None


# ==================== 注册路由 ====================
def register(app):

    @app.before_request
    def _same_origin_only():
        """改状态的请求只接受同源调用。

        本工具监听 127.0.0.1，但"本地"不等于"安全"：你浏览的任意网页都能往
        localhost 发跨站请求。改成 POST-only 已经挡掉 <img src=...> 这类玩法，
        再比对 Origin 就把跨站表单 / fetch 也挡住了。浏览器在跨源请求上必带 Origin；
        少数场景不带（如某些同源导航），此时放行，不影响正常使用。
        """
        if request.method == "GET":
            return None
        origin = request.headers.get("Origin")
        if origin and origin.rstrip("/") != request.host_url.rstrip("/"):
            return jsonify({"success": False, "msg": "跨站请求已被拒绝"}), 403
        return None

    @app.context_processor
    def _inject_globals():
        # 让所有模板都能用 {{ version }}、题单数量（顶栏徽标）与近况统计门槛，各页无需各自传递
        return {"version": config.APP_VERSION, "todo_count": len(todo.load()),
                "min_recent": config.MIN_RECENT_PROBLEMS}

    @app.route("/heartbeat")
    def heartbeat():
        _touch()
        return jsonify({"ok": True})

    @app.route("/shutdown", methods=["POST"])      # sendBeacon 发的就是 POST；限死可挡掉 <img src> 关进程
    def shutdown():
        # 页面关闭时由 navigator.sendBeacon 调用，触发进程快速退出（≤2 秒）
        _request_shutdown()
        return ("", 204)

    @app.route("/", methods=["GET", "POST"])
    def index():
        _touch()
        data, errors = [], []
        contest_type = "Div.2"
        prefill      = ""

        if request.method == "POST":
            handles      = request.form.get("handles", "").replace("，", ",").strip()
            contest_type = request.form.get("contest_type", "Div.2")
            prefill      = handles
            hlist = [x.strip() for x in handles.split(",") if x.strip()]
            valid   = [h for h in hlist if cf_api.is_valid_handle(h)]
            errors += [h for h in hlist if not cf_api.is_valid_handle(h)]   # 非法格式直接判失败
            # 多个用户并行分析（每人内部 3 接口又并行），整体受全局信号量限流
            results = _parallel_map(lambda h: (h, _analyze_handle(h, contest_type)), valid)
            for h, res in results:
                (data.append(res) if res else errors.append(h))

        # 取所有已查询用户的并集：多人查询时不该只按第一个人的等级来高亮
        rec_levels = set()
        for u in data:
            rec_levels |= config.recommended_levels(u["rating"])

        return render_template(
            "index.html",
            version           = config.APP_VERSION,
            data              = data,
            errors            = errors,
            contest_type      = contest_type,
            contest_types     = config.CONTEST_TYPES,
            prefill           = prefill,
            upcoming_contests = contests.get_upcoming_contests(),
            army              = army.load_army(),
            difficulty_bands  = config.DIFFICULTY_BANDS,
            rank_colors       = config.RANK_COLORS,
            rec_levels        = list(rec_levels),
        )

    @app.route("/api/add_army", methods=["POST"])
    def add_army_route():
        handle = request.args.get("handle", "").strip()
        if not handle:
            return jsonify({"success": False, "msg": "用户名不能为空"})
        ok, msg = army.add_to_army(handle)
        return jsonify({"success": ok, "msg": msg})

    @app.route("/api/remove_army", methods=["POST"])
    def remove_army_route():
        handle = request.args.get("handle", "").strip()
        if not handle:
            return jsonify({"success": False, "msg": "用户名不能为空"})
        ok, msg = army.remove_from_army(handle)
        return jsonify({"success": ok, "msg": msg})

    @app.route("/api/refresh_army", methods=["POST"])
    def refresh_army_route():
        ok, total = army.refresh_army()
        msg = f"已刷新 {ok}/{total} 名队友" if total else "大部队暂无成员"
        return jsonify({"success": True, "msg": msg})

    # ==================== 刷题器 ====================
    @app.route("/picker")
    def picker():
        _touch()
        return render_template(
            "picker.html",
            tags=cf_api.all_tags(),
            difficulty_bands=config.DIFFICULTY_BANDS,
            default_count=config.PICK_DEFAULT_COUNT,
        )

    @app.route("/api/pick")
    def api_pick():
        _touch()
        if not cf_api.PROBLEMS:
            return jsonify({"success": False, "msg": "题库仍在后台加载，请几秒后重试"})
        try:
            rmin = int(request.args.get("rating_min", 800))
            rmax = int(request.args.get("rating_max", 3500))
        except ValueError:
            return jsonify({"success": False, "msg": "难度区间需为数字"})
        if rmin > rmax:
            rmin, rmax = rmax, rmin                 # 容错：区间写反自动纠正
        tags  = [t for t in request.args.get("tags", "").split(",") if t.strip()]
        mode  = request.args.get("mode", "random")
        try:
            count = int(request.args.get("count", config.PICK_DEFAULT_COUNT))
        except ValueError:
            count = config.PICK_DEFAULT_COUNT

        solved = set()
        exclude = request.args.get("exclude", "").strip()
        if exclude:
            if not cf_api.is_valid_handle(exclude):
                return jsonify({"success": False, "msg": f"用户名 {exclude} 格式非法"})
            subs = cf_api.get_submissions(exclude)
            if subs is None:
                return jsonify({"success": False, "msg": f"用户 {exclude} 查询失败，无法排除已做题"})
            solved = analysis.solved_keys_of(subs)

        probs, pool_total = analysis.pick_problems(rmin, rmax, tags, solved, mode, count, with_total=True)
        return jsonify({"success": True, "problems": probs, "count": len(probs),
                        "pool_total": pool_total, "excluded": len(solved)})

    # ==================== 组队作战板 ====================
    @app.route("/team", methods=["GET", "POST"])
    def team():
        _touch()
        result, errors, prefill = None, [], ""
        if request.method == "POST":
            handles = request.form.get("handles", "").replace("，", ",").strip()
            prefill = handles
            hlist = [x.strip() for x in handles.split(",") if x.strip()][:config.TEAM_MAX_SIZE]
            errors += [h for h in hlist if not cf_api.is_valid_handle(h)]
            hlist  = [h for h in hlist if cf_api.is_valid_handle(h)]
            fetched = _parallel_map(lambda h: (h, _fetch_member(h)), hlist)
            members = []
            for h, m in fetched:
                (members.append(m) if m else errors.append(h))
            if members:
                result = analysis.analyze_team(members)
                ratings = [m["rating"] for m in members]
                avg = sum(ratings) // len(ratings)
                lo, hi = max(800, avg - 100), avg + 400
                result["practice"] = analysis.recommend_problems(
                    lo, hi, result["weak_tags"], result["union"], limit=12)
                result["practice_range"] = [lo, hi]
                result.pop("union", None)      # set 不进模板
        return render_template("team.html", result=result, errors=errors,
                               prefill=prefill, army=army.load_army(),
                               team_max=config.TEAM_MAX_SIZE)

    # ==================== 个人 vs 队友 head-to-head 对比 ====================
    @app.route("/vs", methods=["GET", "POST"])
    def vs():
        _touch()
        result, errors = None, []
        prefill_a = prefill_b = ""
        if request.method == "POST":
            a = request.form.get("handle_a", "").strip()
            b = request.form.get("handle_b", "").strip()
            prefill_a, prefill_b = a, b
            if not a or not b:
                errors.append("请填写两个用户名")
            elif a.lower() == b.lower():
                errors.append("两个用户名不能相同")
            else:
                errors += [h for h in (a, b) if not cf_api.is_valid_handle(h)]
                if not errors:
                    ua, ub = _parallel_map(_fetch_compare, [a, b])
                    if not ua:
                        errors.append(f"{a} 查询失败")
                    if not ub:
                        errors.append(f"{b} 查询失败")
                    if ua and ub:
                        result = analysis.compare_users(ua, ub)
        return render_template("vs.html", result=result, errors=errors,
                               prefill_a=prefill_a, prefill_b=prefill_b,
                               army=army.load_army())

    # ==================== 题单 / 待做收藏 ====================
    @app.route("/todo")
    def todo_page():
        _touch()
        items   = todo.load()
        pending = [i for i in items if not i.get("done")]
        done    = [i for i in items if i.get("done")]
        return render_template("todo.html", items=items, pending=pending, done=done)

    @app.route("/api/todo/add", methods=["POST"])
    def api_todo_add():
        a = request.args
        try:
            rating = int(a.get("rating", 0))
        except ValueError:
            rating = 0
        tags = [t for t in a.get("tags", "").split(",") if t.strip()]
        ok, msg = todo.add(a.get("key", "").strip(), a.get("name", "").strip(), rating, tags)
        return jsonify({"success": ok, "msg": msg})

    @app.route("/api/todo/remove", methods=["POST"])
    def api_todo_remove():
        ok, msg = todo.remove(request.args.get("key", "").strip())
        return jsonify({"success": ok, "msg": msg})

    @app.route("/api/todo/toggle", methods=["POST"])
    def api_todo_toggle():
        ok, msg = todo.toggle(request.args.get("key", "").strip())
        return jsonify({"success": ok, "msg": msg})

    @app.route("/api/todo/clear_done", methods=["POST"])
    def api_todo_clear():
        n = todo.clear_done()
        return jsonify({"success": True, "msg": f"已清空 {n} 道已完成"})
