# -*- coding: utf-8 -*-
"""计算核心：等级 / 难度 / 刷题统计 / 近况标签 / Elo 预测 / 训练计划 / 题目推荐。

全部为纯函数（除题库缓存只读），输入数据、输出结果，便于单测。
"""
import datetime
import math
import random
import time
from collections import defaultdict

from . import cf_api, config


def solved_keys_of(submissions):
    """从提交记录提取已 AC 的去重题目 key 集合。"""
    keys = set()
    for s in submissions:
        if s.get("verdict") == "OK":
            p = s["problem"]
            keys.add(f"{p.get('contestId')}_{p.get('index')}")
    return keys


# ==================== 等级与升级进度 ====================
def get_rank_info(rating):
    rating = int(rating)
    idx = len(config.CF_RANK_CONFIG) - 1
    cur = config.CF_RANK_CONFIG[-1]
    for i, rank in enumerate(config.CF_RANK_CONFIG):
        if rank["min"] <= rating <= rank["max"]:
            cur, idx = rank, i
            break

    is_max     = (idx == 0)
    nxt        = None if is_max else config.CF_RANK_CONFIG[idx - 1]
    need       = 0 if is_max else nxt["min"] - rating
    cur_min    = cur["min"]
    cur_max    = nxt["min"] if nxt else cur["max"]
    span       = cur_max - cur_min
    progress   = round(max(0, min(100, (rating - cur_min) / span * 100)), 1) if span > 0 else 100

    return {
        "current_name":   cur["name"],
        "current_color":  cur["color_class"],
        "next_name":      nxt["name"] if nxt else "无",
        "need_rating":    need,
        "is_max":         is_max,
        "current_rating": rating,
        "progress":       progress,
    }


def get_difficulty_band(rating):
    for b in config.DIFFICULTY_BANDS:
        if b["min"] <= rating <= b["max"]:
            return b
    return {"name": "未知", "cls": "d-unknown", "desc": "?"}


def _sorted(d):
    return sorted(d.items(), key=lambda x: x[1], reverse=True)


# ==================== 刷题统计（基于一次 user.status） ====================
def analyze_problems(submissions):
    """统计 AC 题数、正确率、各难度档标签分布、难度直方图、已解题集合。

    难度优先用提交里自带的 problem.rating，缺失时回退题库缓存——比旧版仅依赖
    缓存更稳，缓存加载失败时也能正常分级。
    """
    ac_keys      = set()
    total_sub    = len(submissions)
    tags_total   = defaultdict(int)
    buckets      = {lvl: defaultdict(int) for lvl in config.SIMPLE_LEVELS}
    tags_by_band = defaultdict(lambda: defaultdict(int))
    band_solved  = defaultdict(int)

    for s in submissions:
        if s.get("verdict") != "OK":
            continue
        p   = s["problem"]
        key = f"{p.get('contestId')}_{p.get('index')}"
        if key in ac_keys:
            continue
        ac_keys.add(key)

        tags = p.get("tags", [])
        for t in tags:
            tags_total[t] += 1

        pr = p.get("rating") or cf_api.problem_rating(key, 0)
        if pr and pr > 0:
            band = get_difficulty_band(pr)
            band_solved[band["name"]] += 1
            lvl = config.simple_level(pr)
            for t in tags:
                tags_by_band[band["name"]][t] += 1
                buckets[lvl][t] += 1

    ac   = len(ac_keys)
    rate = round(ac / total_sub * 100, 1) if total_sub else 0

    histogram = [{
        "name": b["name"], "cls": b["cls"], "desc": b["desc"],
        "count": band_solved.get(b["name"], 0),
    } for b in config.DIFFICULTY_BANDS]
    hist_max = max((h["count"] for h in histogram), default=0)

    return {
        "submit":       total_sub,
        "ac":           ac,
        "rate":         rate,
        "tags":         _sorted(tags_total),
        "tags_easy":    _sorted(buckets["简单"]),
        "tags_medium":  _sorted(buckets["中等"]),
        "tags_hard":    _sorted(buckets["困难"]),
        "tags_vhard":   _sorted(buckets["极难"]),
        "tags_by_band": {k: _sorted(v) for k, v in tags_by_band.items()},
        "histogram":    histogram,
        "histogram_max": hist_max,
        "solved_keys":  ac_keys,
        "rated_solved": sum(band_solved.values()),
    }


# ==================== 近 N 月标签正确率（修复旧版恒为 0 的 bug） ====================
def analyze_recent_tags(submissions, days=None):
    """近况标签表现：以"去重题目"为口径统计正确率。

    旧版把 ac_rate 计算循环删成了一行注释，导致正确率永远是 0；这里按
    「该标签下尝试过的不同题目中、解出的比例」重新实现，更贴近真实手感。
    """
    days   = days or config.RECENT_DAYS
    cutoff = time.time() - days * 86400

    probs = {}   # key -> {tags, solved, attempts, wa, tle}
    for s in submissions:
        if s.get("creationTimeSeconds", 0) < cutoff:
            continue
        p   = s["problem"]
        key = f"{p.get('contestId')}_{p.get('index')}"
        rec = probs.setdefault(key, {
            "tags": p.get("tags", []), "solved": False,
            "attempts": 0, "wa": 0, "tle": 0,
        })
        rec["attempts"] += 1
        v = s.get("verdict", "")
        if   v == "OK":                   rec["solved"] = True
        elif v == "WRONG_ANSWER":         rec["wa"] += 1
        elif v == "TIME_LIMIT_EXCEEDED":  rec["tle"] += 1

    tag = defaultdict(lambda: {"problems": 0, "solved": 0, "wa": 0, "tle": 0})
    for rec in probs.values():
        for t in rec["tags"]:
            tag[t]["problems"] += 1
            tag[t]["solved"]   += 1 if rec["solved"] else 0
            tag[t]["wa"]       += rec["wa"]
            tag[t]["tle"]      += rec["tle"]

    out = {}
    for t, st in tag.items():
        ac_rate = round(st["solved"] / st["problems"] * 100, 1) if st["problems"] else 0
        out[t] = {
            "total_submit": st["problems"],   # 去重题目数（沿用旧字段名，模板兼容）
            "ac_count":     st["solved"],
            "wa_count":     st["wa"],
            "tle_count":    st["tle"],
            "ac_rate":      ac_rate,
        }
    return dict(sorted(out.items(), key=lambda x: x[1]["total_submit"], reverse=True))


# ==================== 最近比赛 / Rating 走势 ====================
def recent_contests(rating_history, n=5):
    """最近 n 场（user.rating 已修正端点），最新在前。"""
    return list(reversed(rating_history[-n:]))


# ==================== Elo 比赛预测 ====================
def _win_prob(ra, rb):
    return 1.0 / (1 + math.pow(10, (rb - ra) / 400.0))


def _expected_seed(rating, avg_rating, total):
    return max(1, total - total * _win_prob(rating, avg_rating))


def _performance(actual_rank, total, avg_rating):
    lo, hi = 0, 4000
    for _ in range(100):
        mid = (lo + hi) / 2
        if _expected_seed(mid, avg_rating, total) < actual_rank:
            hi = mid
        else:
            lo = mid
    return int(round(lo))


def generate_prediction(user_rating, contest_type):
    cfg   = config.CONTEST_CALIBRATION.get(contest_type, config.CONTEST_CALIBRATION["Div.2"])
    total = cfg["avg_participants"]
    avg   = cfg["avg_contest_rating"]
    out   = {}
    for ac_num, pct in cfg["ac_to_rank_pct"].items():
        rank  = max(1, int(total * pct / 100))
        perf  = _performance(rank, total, avg)
        delta = int(round((perf - user_rating) / 2))
        new_r = max(0, user_rating + delta)
        out[ac_num] = {
            "rank":          rank,
            "rank_pct":      pct,
            "performance":   perf,
            "rating_change": delta,
            "new_rating":    new_r,
            "rank_info":     get_rank_info(new_r),
        }
    return out


# ==================== 训练计划 ====================
def generate_training_plan(user_rating, recent_tags):
    # 未评级用户 CF 不返回 rating 字段，上游填 0——但 0 不代表"比 800 还弱"，
    # 直接套偏移会算出 800 ~ -200 的倒挂区间，推荐池 lo>hi 恒为空。按基准分规划并标记出来。
    real_rating = int(user_rating)
    unrated     = real_rating <= 0
    plan_rating = config.UNRATED_PLAN_RATING if unrated else real_rating

    z = config.TRAINING_ZONE_RULE

    def _zone(key):
        """算一个训练区间。下界顶在题库最低分，上界再兜一次底——
        真实低分用户（<1000）的 comfort 上界本身就低于 800，不兜会倒挂。"""
        lo = max(config.MIN_PROBLEM_RATING, plan_rating + z[key]["min_offset"])
        hi = max(lo, plan_rating + z[key]["max_offset"])
        return {"min": lo, "max": hi, "desc": z[key]["desc"]}

    comfort, improve, challenge = _zone("comfort"), _zone("improve"), _zone("challenge")
    i_lo, i_hi = improve["min"], improve["max"]

    if plan_rating < 1600:
        contest_match = [
            {"zone": "comfort",   "contest": "Div.3", "problems": "A-B-C"},
            {"zone": "improve",   "contest": "Div.3", "problems": "D-E-F | Div.2 A-B-C"},
            {"zone": "challenge", "contest": "Div.2", "problems": "D-E"},
        ]
    elif plan_rating < 2100:
        contest_match = [
            {"zone": "comfort",   "contest": "Div.2", "problems": "A-B-C"},
            {"zone": "improve",   "contest": "Div.2", "problems": "D-E-F | Div.1 A-B"},
            {"zone": "challenge", "contest": "Div.1", "problems": "C-D"},
        ]
    elif plan_rating < 2600:
        contest_match = [
            {"zone": "comfort",   "contest": "Div.1", "problems": "A-B"},
            {"zone": "improve",   "contest": "Div.1", "problems": "C-D-E"},
            {"zone": "challenge", "contest": "Div.1", "problems": "F | 2500+难题"},
        ]
    else:
        contest_match = [
            {"zone": "comfort",   "contest": "Div.1",    "problems": "A-B-C-D"},
            {"zone": "improve",   "contest": "Div.1",    "problems": "E-F"},
            {"zone": "challenge", "contest": "ICPC/IOI", "problems": "金牌题"},
        ]

    # 基于"近况正确率"识别薄弱 / 强项（依赖已修复的 ac_rate）
    weak_tags, strong_tags = [], []
    for tag, rd in recent_tags.items():
        if rd["total_submit"] < config.MIN_RECENT_PROBLEMS:
            continue
        if rd["ac_rate"] < config.WEAK_AC_RATE:
            weak_tags.append(tag)
        elif rd["ac_rate"] >= config.STRONG_AC_RATE:
            strong_tags.append(tag)

    return {
        "user_rating": real_rating,
        "plan_rating": plan_rating,     # 未评级时 = 基准分，其余等于 user_rating
        "unrated":     unrated,         # 模板据此提示"计划按基准分给出"
        "zones": {
            "comfort":   comfort,
            "improve":   improve,
            "challenge": challenge,
        },
        "contest_match": contest_match,
        "strong_tags":   strong_tags[:4],
        "weak_tags":     weak_tags[:6],
        "core_suggestion": (
            f"核心训练：主攻 {i_lo}-{i_hi} 分区间，"
            + (f"优先补全【{ '、'.join(weak_tags[:3]) }】等薄弱标签"
               if weak_tags else "近况无明显薄弱标签，保持节奏拔高难度")
        ),
    }


# ==================== 个性化题目推荐（提升区内、未做过、命中薄弱标签） ====================
def recommend_problems(lo, hi, weak_tags, solved_keys, limit=None):
    limit = limit or config.RECOMMEND_LIMIT
    if not cf_api.PROBLEMS:
        return []

    weakset = set(weak_tags or [])
    pool = [p for p in cf_api.PROBLEMS
            if lo <= p["rating"] <= hi and p["key"] not in solved_keys]
    if not pool:
        return []

    matched = [p for p in pool if weakset & set(p["tags"])] if weakset else []
    chosen  = matched if matched else pool
    chosen  = sorted(chosen, key=lambda p: (p["rating"], p["key"]))

    # 在难度区间内均匀取样，避免推荐扎堆在最低分
    if len(chosen) > limit:
        step    = len(chosen) / limit
        chosen  = [chosen[int(i * step)] for i in range(limit)]
    else:
        chosen = chosen[:limit]

    return [{
        "key":    p["key"],
        "name":   p["name"],
        "rating": p["rating"],
        "tags":   p["tags"],
        "hit":    sorted(weakset & set(p["tags"])),
        "url":    f"https://codeforces.com/problemset/problem/{p['contest_id']}/{p['index']}",
    } for p in chosen]


# ==================== 弱点墙：每个难度档的真实通过率 → 能力天花板 ====================
def analyze_weakness_wall(submissions):
    """按难度档统计「尝试 vs 解出」的去重题目数与真实通过率。

    与"刷题画像"只数 AC 不同，这里把没解出来的尝试也计入分母，于是能看出
    通过率在哪一档开始崩——那就是你的"墙"，也是 rating 想涨最该主攻的难度。
    """
    # 单遍去重：每个题目记录难度与是否解出
    probs = {}   # key -> {rating, solved}
    for s in submissions:
        p   = s["problem"]
        key = f"{p.get('contestId')}_{p.get('index')}"
        pr  = p.get("rating") or cf_api.problem_rating(key, 0)
        if not pr or pr <= 0:
            continue
        rec = probs.setdefault(key, {"rating": pr, "solved": False})
        if s.get("verdict") == "OK":
            rec["solved"] = True

    # 单遍按难度档桶计（避免每档重扫一遍 probs）
    counts = {b["name"]: [0, 0] for b in config.DIFFICULTY_BANDS}   # name -> [尝试, 解出]
    for rec in probs.values():
        c = counts[get_difficulty_band(rec["rating"])["name"]]
        c[0] += 1
        c[1] += 1 if rec["solved"] else 0

    rows = []
    for b in config.DIFFICULTY_BANDS:                              # 难 → 易
        att, sol = counts[b["name"]]
        rate = round(sol / att * 100, 1) if att else None
        rows.append({"name": b["name"], "cls": b["cls"], "desc": b["desc"],
                     "min": b["min"], "max": b["max"],
                     "attempted": att, "solved": sol, "rate": rate})
    ordered = list(reversed(rows))                                 # 易 → 难，符合阅读直觉

    reliable = [r for r in ordered if r["attempted"] >= config.WALL_MIN_ATTEMPTS]
    ceiling = None
    for r in reliable:               # 最高的"通过率仍达标"档 = 稳固上限
        if r["rate"] is not None and r["rate"] >= config.WALL_WALL_RATE:
            ceiling = r
    wall = None
    if ceiling:
        ci = ordered.index(ceiling)
        # 上限往上、第一个"可信"档 = 墙。这里同样要卡 WALL_MIN_ATTEMPTS：
        # 只碰过 1-2 题的档算出的 0% 是噪声，拿它当结论会误导训练方向。
        # 又因为 ceiling 已取到最高的达标档，上面任何可信档的通过率必然 < WALL_WALL_RATE。
        for r in ordered[ci + 1:]:
            if r["attempted"] >= config.WALL_MIN_ATTEMPTS:
                wall = r
                break

    t_min, t_max = _wall_target(ceiling, wall)
    return {
        "rows":      ordered,
        "ceiling":   ceiling["name"] if ceiling else None,
        "wall":      wall["name"] if wall else None,
        # 给"刷题器"用的目标分段：优先墙，其次稳固上限往上一档，便于一键深链去练
        "target_min": t_min,
        "target_max": t_max,
        "verdict":   _wall_verdict(ceiling, wall, reliable),
    }


def _wall_target(ceiling, wall):
    """算"🎯 去刷题器练这一档"的目标分段，并钳在题库真实存在的难度范围内。

    最高难度档的 max 是 9999（分档开口，不是真有题）；旧版无墙时直接用 ceiling.max+1，
    对已练到顶档的用户会算出 10000~10199 这种区间，深链过去必然出 0 道题。
    """
    if wall:
        return wall["min"], wall["max"]
    if not ceiling:
        return None, None
    lo = ceiling["max"] + 1
    if lo > config.MAX_PROBLEM_RATING:
        # 已经站在题库最高档，上面没有更难的题了 —— 就在这一档继续加量
        return max(ceiling["min"], config.MIN_PROBLEM_RATING), config.MAX_PROBLEM_RATING
    return lo, min(ceiling["max"] + 200, config.MAX_PROBLEM_RATING)


def _wall_verdict(ceiling, wall, reliable):
    if not reliable:
        return "带难度分的尝试题太少，统计还不可信——多刷几场带 rating 的题再回来看。"
    if ceiling and wall:
        wr = wall["rate"] if wall["rate"] is not None else "~"
        return (f"稳固上限在【{ceiling['name']} {ceiling['desc']}】（通过率 {ceiling['rate']}%），"
                f"墙在【{wall['name']} {wall['desc']}】（通过率 {wr}%）。"
                f"主攻这一档、把通过率练上去，rating 会跟着上来。")
    if ceiling and not wall:
        return (f"最高稳固档是【{ceiling['name']} {ceiling['desc']}】，再往上还没有哪一档"
                f"攒够 {config.WALL_MIN_ATTEMPTS} 道尝试，墙还没显形——"
                f"别在舒适区原地刷了，往更高难度多试几题。")
    return (f"各档通过率都还不稳，先回到【{reliable[0]['name']} {reliable[0]['desc']}】"
            f"把基本功打扎实，再逐档上推。")


# ==================== 刷题器：从全站题库按条件出题 ====================
def pick_problems(rating_min, rating_max, tags=None, solved_keys=None,
                  mode="random", count=None, with_total=False):
    """在题库里按 难度区间 + 标签(任一命中) + 未做过 出题。mode: random | sorted。

    with_total=True 时返回 (题目列表, 命中题库总数)，便于前端提示"从 N 题中抽取"。
    """
    count  = max(1, min(count or config.PICK_DEFAULT_COUNT, config.PICK_MAX_COUNT))
    def _ret(lst, total):
        return (lst, total) if with_total else lst

    if not cf_api.PROBLEMS:
        return _ret([], 0)
    tagset = set(tags or [])
    solved = solved_keys or set()
    pool = [p for p in cf_api.PROBLEMS
            if rating_min <= p["rating"] <= rating_max
            and p["key"] not in solved
            and (not tagset or (tagset & set(p["tags"])))]
    if not pool:
        return _ret([], 0)
    if mode == "random":
        chosen = random.sample(pool, min(count, len(pool)))
        chosen.sort(key=lambda p: p["rating"])
    else:
        chosen = sorted(pool, key=lambda p: (p["rating"], p["key"]))[:count]
    out = [{
        "key":    p["key"],
        "name":   p["name"],
        "rating": p["rating"],
        "tags":   p["tags"],
        "url":    f"https://codeforces.com/problemset/problem/{p['contest_id']}/{p['index']}",
    } for p in chosen]
    return _ret(out, len(pool))


# ==================== 团队作战板：技能矩阵 / 分工 / 共同弱项 ====================
def analyze_team(members):
    """输入每个成员的 {handle, rating, rank_info, tag_counts, solved_keys}，
    产出：标签技能矩阵、按标签的最优人选（分工建议）、全队共同弱项、并集已解题。
    """
    union = set()
    total_tag = defaultdict(int)
    for m in members:
        union |= m["solved_keys"]
        for t, c in m["tag_counts"].items():
            total_tag[t] += c

    top_tags = [t for t, _ in sorted(total_tag.items(), key=lambda x: -x[1])][:config.TEAM_MATRIX_TAGS]

    matrix, assignment, weak_tags = [], {}, []
    for t in top_tags:
        cells = [{"handle": m["handle"], "count": m["tag_counts"].get(t, 0)} for m in members]
        best_count = max(c["count"] for c in cells)
        for c in cells:
            c["best"] = (c["count"] == best_count and best_count > 0)
        best_handle = next((c["handle"] for c in cells if c["best"]), None)
        matrix.append({"tag": t, "cells": cells, "team_total": total_tag[t], "best": best_handle})
        if best_handle:
            assignment.setdefault(best_handle, []).append(t)
        if best_count < config.TEAM_WEAK_BEST_MAX:   # 连最强者都很少 → 全队弱项
            weak_tags.append(t)

    return {
        "members":   [{"handle": m["handle"], "rating": m["rating"],
                       "rank_info": m["rank_info"]} for m in members],
        "matrix":     matrix,
        "assignment": assignment,
        "weak_tags":  weak_tags,
        "union_size": len(union),
        "union":      union,
    }


# ==================== 个人 vs 队友 head-to-head 对比 ====================
def compare_users(a, b):
    """两名选手全方位对比：核心数据 / 难度分布 / 标签强弱 / 已解题集合 /
    同场交锋战绩 / 双线 Rating 走势。a、b 为 routes._fetch_compare 的产物。"""
    def basic(u):
        return {"handle": u["handle"], "rating": u["rating"], "max_rating": u["max_rating"],
                "rank_info": u["rank_info"], "medal_class": u["medal_class"],
                "ac": u["ac"], "submit": u["submit"], "rate": u["rate"]}

    def row(label, av, bv):
        winner = "tie" if av == bv else ("a" if av > bv else "b")
        return {"label": label, "a": av, "b": bv, "winner": winner}

    stat_rows = [
        row("当前 Rating", a["rating"],     b["rating"]),
        row("最高 Rating", a["max_rating"], b["max_rating"]),
        row("总 AC 题数",  a["ac"],         b["ac"]),
        row("正确率 %",    a["rate"],       b["rate"]),
    ]

    # 难度分布（易 → 难，背靠背）
    b_hist = {h["name"]: h["count"] for h in b["histogram"]}
    histogram = [{"name": h["name"], "cls": h["cls"], "desc": h["desc"],
                  "a": h["count"], "b": b_hist.get(h["name"], 0)}
                 for h in reversed(a["histogram"])]
    hist_max = max([max(x["a"], x["b"]) for x in histogram], default=0)

    # 标签强弱（按两人合计取 TOP）
    a_tags, b_tags = dict(a["tags"]), dict(b["tags"])
    tag_rows = [{"tag": t, "a": a_tags.get(t, 0), "b": b_tags.get(t, 0),
                 "leader": "a" if a_tags.get(t, 0) > b_tags.get(t, 0)
                           else ("b" if b_tags.get(t, 0) > a_tags.get(t, 0) else "tie")}
                for t in (set(a_tags) | set(b_tags))]
    tag_rows.sort(key=lambda x: -(x["a"] + x["b"]))
    tag_rows = tag_rows[:config.TEAM_MATRIX_TAGS]

    # 已解题集合
    sa, sb = a["solved_keys"], b["solved_keys"]
    solved = {"common": len(sa & sb), "only_a": len(sa - sb), "only_b": len(sb - sa)}

    # 同场交锋：两人都参加过的比赛里逐场比名次（名次小者胜）
    a_c = {c["contest_id"]: c for c in a["rating_history"]}
    b_c = {c["contest_id"]: c for c in b["rating_history"]}
    a_wins = b_wins = ties = 0
    shared = []
    for cid in set(a_c) & set(b_c):
        ca, cb = a_c[cid], b_c[cid]
        if   ca["rank"] < cb["rank"]: w, a_wins = "a", a_wins + 1
        elif cb["rank"] < ca["rank"]: w, b_wins = "b", b_wins + 1
        else:                         w, ties   = "tie", ties + 1
        shared.append({"name": ca["name"], "time": ca["time"],
                       "a_rank": ca["rank"], "b_rank": cb["rank"], "winner": w})
    shared.sort(key=lambda x: -x["time"])
    contests = {"shared": len(shared), "a_wins": a_wins, "b_wins": b_wins,
                "ties": ties, "recent": shared[:12]}

    return {
        "a": basic(a), "b": basic(b),
        "stat_rows": stat_rows,
        "histogram": histogram, "hist_max": hist_max,
        "tags": tag_rows, "solved": solved, "contests": contests,
        "chart_a": a["rating_history"], "chart_b": b["rating_history"],   # 双线走势用
    }


# ==================== 刷题活跃热力图（GitHub 风格） ====================
_CST = datetime.timezone(datetime.timedelta(hours=8))


def _hm_level(c):
    if c <= 0: return 0
    if c == 1: return 1
    if c <= 3: return 2
    if c <= 6: return 3
    return 4


def activity_heatmap(submissions, days=None):
    """近一年「每天新解出的题数」热力图：以每题最早 AC 那天计数（按 CST 划天），
    输出周一对齐的周列网格 + 月份标签 + 连刷 / 最长连刷 / 活跃天 / 最高产日。"""
    days = days or config.HEATMAP_DAYS

    first_ok = {}                                   # 每题最早 AC 时间
    for s in submissions:
        if s.get("verdict") != "OK":
            continue
        p   = s["problem"]
        key = f"{p.get('contestId')}_{p.get('index')}"
        t   = s.get("creationTimeSeconds", 0)
        if key not in first_ok or t < first_ok[key]:
            first_ok[key] = t

    day_count = defaultdict(int)
    for t in first_ok.values():
        day_count[datetime.datetime.fromtimestamp(t, tz=_CST).date()] += 1

    today = datetime.datetime.now(tz=_CST).date()
    start = today - datetime.timedelta(days=days - 1)
    start -= datetime.timedelta(days=start.weekday())     # 回退到所在周的周一（Mon=0）

    cells, d, one = [], start, datetime.timedelta(days=1)
    while d <= today:
        c = day_count.get(d, 0)
        cells.append({"d": d.isoformat(), "c": c, "lv": _hm_level(c), "_m": d.month})
        d += one
    while len(cells) % 7:                                  # 补齐最后一周（未来日期置 None）
        cells.append(None)
    weeks = [cells[i:i + 7] for i in range(0, len(cells), 7)]

    week_months, prev = [], None                          # 每列首个有效格的月份，变化才标注
    for wk in weeks:
        first = next((c for c in wk if c), None)
        m = first["_m"] if first else None
        week_months.append(f"{m}月" if (m and m != prev) else "")
        if m: prev = m
    for c in cells:                                       # _m 用完即弃
        if c: c.pop("_m", None)

    valid = [c for c in cells if c]
    total = sum(c["c"] for c in valid)
    active_days = sum(1 for c in valid if c["c"] > 0)
    longest = cur = 0
    for c in valid:
        cur = cur + 1 if c["c"] > 0 else 0
        longest = max(longest, cur)
    current = cur                                         # valid 以今天结尾，尾段连续即当前连刷
    mx = max(valid, key=lambda c: c["c"]) if valid else None
    max_day = {"date": mx["d"], "count": mx["c"]} if (mx and mx["c"] > 0) else {"date": "", "count": 0}

    return {
        "weeks": weeks, "week_months": week_months,
        "total": total, "active_days": active_days,
        "current_streak": current, "longest_streak": longest,
        "max_day": max_day, "days": days,
    }
