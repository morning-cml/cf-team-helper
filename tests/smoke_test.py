# -*- coding: utf-8 -*-
"""冒烟测试：纯函数（离线，秒级）+ 可选实网测试。

用法：
    python tests/smoke_test.py          # 仅离线纯函数测试
    python tests/smoke_test.py --net     # 额外跑实网端到端测试
"""
import os
import sys
import time

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="backslashreplace")
    except Exception:
        pass

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from cfhelper import analysis, cf_api, config


def test_rank_info():
    ri = analysis.get_rank_info(1850)
    assert ri["current_name"] == "候选大师"
    assert ri["next_name"] == "大师"
    assert ri["need_rating"] == 150
    assert analysis.get_rank_info(4000)["is_max"] is True


def test_difficulty_band():
    assert analysis.get_difficulty_band(800)["name"] == "入门"
    assert analysis.get_difficulty_band(1500)["name"] == "中等+"
    assert analysis.get_difficulty_band(3200)["name"] == "神级"


def _fake_subs():
    now = int(time.time())
    return [
        {"verdict": "WRONG_ANSWER", "creationTimeSeconds": now - 100,
         "problem": {"contestId": 1, "index": "A", "tags": ["dp"], "rating": 1500, "name": "A"}},
        {"verdict": "OK", "creationTimeSeconds": now - 90,
         "problem": {"contestId": 1, "index": "A", "tags": ["dp"], "rating": 1500, "name": "A"}},
        {"verdict": "WRONG_ANSWER", "creationTimeSeconds": now - 80,
         "problem": {"contestId": 2, "index": "B", "tags": ["dp"], "rating": 1600, "name": "B"}},
        {"verdict": "OK", "creationTimeSeconds": now - 70,
         "problem": {"contestId": 3, "index": "C", "tags": ["greedy"], "rating": 900, "name": "C"}},
        {"verdict": "OK", "creationTimeSeconds": now - 200 * 86400,
         "problem": {"contestId": 4, "index": "D", "tags": ["math"], "rating": 2000, "name": "D"}},
    ]


def test_analyze_problems():
    prob = analysis.analyze_problems(_fake_subs())
    assert prob["ac"] == 3                 # A, C, D 去重
    assert prob["rated_solved"] == 3


def test_recent_ac_rate_not_zero():
    """回归守护：旧版 ac_rate 恒为 0 的 bug 不能复现。"""
    recent = analysis.analyze_recent_tags(_fake_subs())
    assert recent["dp"]["total_submit"] == 2   # 近况尝试 A、B 两题
    assert recent["dp"]["ac_count"] == 1       # 解出 A
    assert recent["dp"]["ac_rate"] == 50.0     # 关键：不是 0
    assert recent["greedy"]["ac_rate"] == 100.0
    assert "math" not in recent               # 200 天前，超出窗口


def test_prediction_shape():
    pred = analysis.generate_prediction(1850, "Div.2")
    assert set(pred.keys()) == set(range(0, 7))
    assert all("new_rating" in v for v in pred.values())


def test_solved_keys_of():
    keys = analysis.solved_keys_of(_fake_subs())
    assert keys == {"1_A", "3_C", "4_D"}     # 仅 OK 的去重题


def _wall_subs():
    now = int(time.time())
    def s(v, cid, idx, r):
        return {"verdict": v, "creationTimeSeconds": now,
                "problem": {"contestId": cid, "index": idx, "tags": ["x"], "rating": r, "name": idx}}
    return [s("OK", 1, "A", 900), s("OK", 2, "B", 1000),
            s("WRONG_ANSWER", 2, "B", 1000),          # 同题，仍算解出
            s("WRONG_ANSWER", 3, "C", 1600),          # 中等+ 尝试未解出
            s("WRONG_ANSWER", 3, "C", 1600)]


def test_weakness_wall():
    w = analysis.analyze_weakness_wall(_wall_subs())
    by = {r["name"]: r for r in w["rows"]}
    assert by["简单"]["attempted"] == 2 and by["简单"]["solved"] == 2 and by["简单"]["rate"] == 100.0
    # 尝试过但没解出 → 通过率是 0.0 而不是 None（分母含失败尝试，正是弱点墙的意义）
    assert by["中等+"]["attempted"] == 1 and by["中等+"]["solved"] == 0 and by["中等+"]["rate"] == 0.0
    assert w["rows"][0]["name"] == "入门"        # 输出顺序为易→难


def test_pick_problems():
    fake = [
        {"key": "1_A", "contest_id": 1, "index": "A", "name": "A", "rating": 1200, "tags": ["dp"]},
        {"key": "2_B", "contest_id": 2, "index": "B", "name": "B", "rating": 1400, "tags": ["greedy"]},
        {"key": "3_C", "contest_id": 3, "index": "C", "name": "C", "rating": 1800, "tags": ["dp", "graphs"]},
    ]
    saved = list(cf_api.PROBLEMS)
    cf_api.PROBLEMS[:] = fake
    try:
        r1 = analysis.pick_problems(1000, 1500, ["dp"], set(), mode="sorted")
        assert [p["rating"] for p in r1] == [1200]                 # 区间+标签命中
        r2 = analysis.pick_problems(1000, 2000, None, {"1_A"}, mode="sorted")
        assert [p["rating"] for p in r2] == [1400, 1800]           # 排除已做过的 1_A
    finally:
        cf_api.PROBLEMS[:] = saved


def test_analyze_team():
    mk = lambda h, r, tc, sk: {"handle": h, "rating": r,
                               "rank_info": analysis.get_rank_info(r),
                               "tag_counts": tc, "solved_keys": sk}
    members = [mk("A", 1500, {"dp": 10, "greedy": 2}, {"1_A", "2_B"}),
               mk("B", 1600, {"dp": 3, "greedy": 8}, {"2_B", "3_C"})]
    team = analysis.analyze_team(members)
    assert team["union_size"] == 3                                 # {1_A,2_B,3_C}
    best = {r["tag"]: r["best"] for r in team["matrix"]}
    assert best["dp"] == "A" and best["greedy"] == "B"             # 各标签最强者
    assert "dp" in team["assignment"]["A"] and "greedy" in team["assignment"]["B"]


def test_valid_handle():
    ok = cf_api.is_valid_handle
    assert ok("tourist") and ok("a_b-c.d") and ok("X1")
    assert not ok("") and not ok("a b") and not ok("a,b") and not ok("x" * 25)


def test_analyze_handle_error_isolated():
    """单人分析内部异常应被吞成 None（不连累并行里的其他人 / 整页 500）。"""
    import cfhelper.routes as routes
    orig = cf_api.fetch_user_bundle
    cf_api.fetch_user_bundle = lambda h: (_ for _ in ()).throw(RuntimeError("boom"))
    try:
        assert routes._analyze_handle("whoever", "Div.2") is None
        assert routes._fetch_member("whoever") is None
    finally:
        cf_api.fetch_user_bundle = orig


def test_weakness_wall_target():
    now = int(time.time())
    def s(v, cid, idx, r):
        return {"verdict": v, "creationTimeSeconds": now,
                "problem": {"contestId": cid, "index": idx, "tags": ["x"], "rating": r, "name": idx}}
    subs = [s("OK", i, "A", 900 + i * 10) for i in range(5)]          # 简单档 5 题全解出
    subs += [s("WRONG_ANSWER", 100 + i, "B", 1300 + i * 10) for i in range(4)]  # 中等档 4 题
    subs += [s("OK", 100, "B", 1300)]                                 # 其中 1 题解出 → 25%
    w = analysis.analyze_weakness_wall(subs)
    assert w["ceiling"] == "简单" and w["wall"] == "中等"
    assert w["target_min"] == 1300 and w["target_max"] == 1499        # 深链给刷题器的目标分段


def test_wall_needs_enough_attempts():
    """回归守护：只碰过 1-2 题的档不能被判成「墙」。

    旧版找墙的条件是 attempted > 0（WALL_MIN_ATTEMPTS 只卡了稳固上限），
    于是"某档试了 2 题没做出来"就会被斩钉截铁地写进结论，让人照着改训练方向。
    """
    now = int(time.time())
    def s(v, cid, r):
        return {"verdict": v, "creationTimeSeconds": now,
                "problem": {"contestId": cid, "index": "A", "tags": ["x"], "rating": r, "name": "A"}}

    subs = [s("OK", i, 800) for i in range(6)]                 # 入门档 6 题全解出 → 稳固上限
    subs += [s("WRONG_ANSWER", 100 + i, 1000) for i in range(2)]   # 简单档只碰 2 题，样本不足
    w = analysis.analyze_weakness_wall(subs)
    assert w["ceiling"] == "入门"
    assert w["wall"] is None, "样本不足的档不该被判成墙"
    assert str(config.WALL_MIN_ATTEMPTS) in w["verdict"]        # 结论里说明为什么没定出墙

    subs += [s("WRONG_ANSWER", 200 + i, 1000) for i in range(2)]   # 补到 4 题 → 达到可信门槛
    w2 = analysis.analyze_weakness_wall(subs)
    assert w2["wall"] == "简单" and w2["target_min"] == 900 and w2["target_max"] == 1099


def test_wall_target_within_problemset():
    """回归守护：深链目标区间必须落在题库真实存在的难度内（800~3500）。

    最高难度档的 max 是 9999（分档开口，题库里并没有这么难的题）。旧版无墙时用
    ceiling.max + 1，对练到顶档的用户会算出 10000~10199，点过去必然出 0 道题。
    """
    now = int(time.time())
    subs = [{"verdict": "OK", "creationTimeSeconds": now,
             "problem": {"contestId": i, "index": "A", "tags": ["x"], "rating": 3200, "name": "A"}}
            for i in range(6)]                                  # 神级档 6 题全解出，其上再无档位
    w = analysis.analyze_weakness_wall(subs)
    assert w["ceiling"] == "神级" and w["wall"] is None
    assert w["target_min"] <= w["target_max"], "目标区间倒挂"
    assert config.MIN_PROBLEM_RATING <= w["target_min"] <= config.MAX_PROBLEM_RATING
    assert config.MIN_PROBLEM_RATING <= w["target_max"] <= config.MAX_PROBLEM_RATING

    # 任何 ceiling/wall 组合下目标区间都不能越界
    for r in (800, 1000, 1500, 2000, 2800, 3200):
        subs = [{"verdict": "OK", "creationTimeSeconds": now,
                 "problem": {"contestId": i, "index": "A", "tags": ["x"], "rating": r, "name": "A"}}
                for i in range(6)]
        t = analysis.analyze_weakness_wall(subs)
        assert t["target_min"] <= t["target_max"] <= config.MAX_PROBLEM_RATING, f"rating={r} 越界"


def test_pick_with_total():
    fake = [{"key": "1_A", "contest_id": 1, "index": "A", "name": "A", "rating": 1200, "tags": ["dp"]},
            {"key": "2_B", "contest_id": 2, "index": "B", "name": "B", "rating": 1300, "tags": ["dp"]}]
    saved = list(cf_api.PROBLEMS)
    cf_api.PROBLEMS[:] = fake
    try:
        lst, total = analysis.pick_problems(1000, 2000, ["dp"], set(), mode="sorted", with_total=True)
        assert total == 2 and len(lst) == 2
    finally:
        cf_api.PROBLEMS[:] = saved


def _cmp_user(handle, rating, ac, tags, solved, hist, rh):
    return {"handle": handle, "rating": rating, "max_rating": rating + 100, "medal_class": "",
            "rank_info": analysis.get_rank_info(rating), "ac": ac, "submit": ac * 2, "rate": 50.0,
            "histogram": hist, "tags": tags, "solved_keys": solved, "rating_history": rh}


def test_compare_users():
    hist = [{"name": "中等", "cls": "d-med1", "desc": "1300-1499", "count": 5}]
    def rh(pairs):   # pairs: [(contest_id, rank)]
        return [{"contest_id": cid, "name": f"R{cid}", "rank": rk, "old_rating": 1500,
                 "new_rating": 1520, "rating_change": 20, "time": 1000 + cid} for cid, rk in pairs]
    a = _cmp_user("A", 1600, 50, [("dp", 10), ("greedy", 2)], {"1_A", "2_B"}, hist, rh([(1, 10), (2, 50)]))
    b = _cmp_user("B", 1550, 40, [("dp", 3), ("greedy", 8), ("math", 4)], {"2_B", "3_C"}, hist, rh([(1, 20), (2, 30)]))
    cmp = analysis.compare_users(a, b)
    assert cmp["contests"]["shared"] == 2 and cmp["contests"]["a_wins"] == 1 and cmp["contests"]["b_wins"] == 1
    assert cmp["solved"] == {"common": 1, "only_a": 1, "only_b": 1}
    leader = {t["tag"]: t["leader"] for t in cmp["tags"]}
    assert leader["dp"] == "a" and leader["greedy"] == "b" and leader["math"] == "b"
    assert cmp["stat_rows"][0]["winner"] == "a"        # A(1600) Rating 高
    assert cmp["chart_a"] and cmp["chart_b"]            # 双线走势数据透传


def test_activity_heatmap():
    now, day = int(time.time()), 86400
    subs = [{"verdict": "OK", "creationTimeSeconds": now,
             "problem": {"contestId": i, "index": "A", "tags": [], "rating": 1000, "name": "x"}}
            for i in range(5)]                                # 今天解出 5 道不同题
    subs.append({"verdict": "OK", "creationTimeSeconds": now - day,
                 "problem": {"contestId": 99, "index": "B", "tags": [], "rating": 1000, "name": "y"}})
    hm = analysis.activity_heatmap(subs)
    assert hm["total"] == 6 and hm["active_days"] == 2
    assert hm["longest_streak"] == 2 and hm["current_streak"] == 2
    assert hm["max_day"]["count"] == 5
    assert all(len(wk) == 7 for wk in hm["weeks"])            # 每列补齐 7 格
    valid = [c for wk in hm["weeks"] for c in wk if c]
    assert max(c["c"] for c in valid) == 5 and any(c["lv"] == 3 for c in valid)   # 5 题/天 → lv3


def test_todo_crud():
    from cfhelper import todo
    from cfhelper.paths import data_path
    orig = config.TODO_FILE
    config.TODO_FILE = "cf_todo_test.json"
    path = data_path(config.TODO_FILE)
    try:
        if os.path.exists(path):
            os.remove(path)
        assert todo.add("1850_A", "Test", 1200, ["dp"])[0] is True
        assert len(todo.load()) == 1 and todo.load()[0]["url"].endswith("/problem/1850/A")
        assert todo.add("1850_A", "Test", 1200, [])[0] is False     # 去重
        assert todo.add("bad", "X")[0] is False                     # key 非法
        assert todo.toggle("1850_A")[0] is True and todo.load()[0]["done"] is True
        assert todo.clear_done() == 1 and todo.load() == []
        assert todo.remove("zzz")[0] is False                       # 不存在
    finally:
        config.TODO_FILE = orig
        if os.path.exists(path):
            os.remove(path)


def test_training_plan_low_and_unrated():
    """回归守护：低分 / 未评级用户的训练区间不能倒挂，推荐题不能恒为空。

    旧版对 rating=0（CF 未评级不返回 rating 字段）算出 comfort = 800 ~ -200，
    improve = -200 ~ 300；routes 再取 max(800, min) 后变成 lo=800 > hi=300，
    推荐池 lo<=r<=hi 恒为空集。rating < 1000 的真实用户同样会倒挂。
    """
    fake = [{"key": f"{i}_A", "contest_id": i, "index": "A", "name": f"P{i}",
             "rating": r, "tags": ["dp"]}
            for i, r in enumerate(range(800, 2001, 100), start=1)]
    saved = list(cf_api.PROBLEMS)
    cf_api.PROBLEMS[:] = fake
    try:
        for rating in (0, 800, 900, 1000, 1100, 1400, 2000):
            plan = analysis.generate_training_plan(rating, {})
            for name, z in plan["zones"].items():
                assert z["min"] <= z["max"], f"rating={rating} 的 {name} 区间倒挂"
                assert z["min"] >= config.MIN_PROBLEM_RATING, f"rating={rating} 的 {name} 下界低于题库最低分"
            imp = plan["zones"]["improve"]
            recos = analysis.recommend_problems(imp["min"], imp["max"], plan["weak_tags"], set())
            assert recos, f"rating={rating} 推荐题为空"
    finally:
        cf_api.PROBLEMS[:] = saved

    unrated = analysis.generate_training_plan(0, {})
    assert unrated["unrated"] is True
    assert unrated["plan_rating"] == config.UNRATED_PLAN_RATING     # 未评级按基准分规划
    rated = analysis.generate_training_plan(1500, {})
    assert rated["unrated"] is False and rated["plan_rating"] == 1500


def test_atomic_json_and_corrupt_backup():
    """原子写 + 损坏留痕：看门狗 os._exit 撞上写入不能留下残缺文件，
    而已损坏的文件必须备份成 .bad，不能被下一次保存静默覆盖掉。"""
    from cfhelper.paths import atomic_write_json, data_path, read_json
    name = "cf_atomic_test.json"
    path = data_path(name)
    for p in (path, path + ".tmp", path + ".bad"):
        if os.path.exists(p):
            os.remove(p)
    try:
        assert read_json(name, []) == []                    # 文件不存在 = 正常首次运行
        atomic_write_json(name, [{"handle": "tourist"}])
        assert read_json(name, []) == [{"handle": "tourist"}]
        assert not os.path.exists(path + ".tmp")            # 临时文件已被 replace 掉

        with open(path, "w", encoding="utf-8") as f:        # 模拟硬退出留下的残缺 JSON
            f.write('[{"handle": "tou')
        assert read_json(name, []) == []                    # 读不动 → 返回默认
        assert os.path.exists(path + ".bad"), "损坏文件必须备份，否则数据静默丢失"
        assert not os.path.exists(path), "损坏文件应已被移走"
    finally:
        for p in (path, path + ".tmp", path + ".bad"):
            if os.path.exists(p):
                os.remove(p)


def test_icpc_classify():
    """ICPC 四档分类：用实测踩过的真实比赛名做回归。

    这些名字全部取自 CF 线上数据，每一条都对应一个曾经分错的坑。
    """
    from cfhelper import icpc
    cases = [
        # —— 应当排除 ——
        ("2019 Google Code Jam World Finals (GCJ 19 World Finals)", None),   # 名字带 World Finals 但非 ICPC
        ("2013-2014 CT S01E04: 2013 Kashan Contest + Some Problems of 2009 GCJ", None),
        ("2025 Xian Jiaotong University Programming Contest", None),        # 只是名字带城市的校赛
        ("Dalian University of Technology, Software College 2025 Freshman Contest", None),
        ("The 2025 CCPC Harbin Onsite Warmup", None),                       # 热身赛不是正赛
        ("2016-2017 National Taiwan University World Final Team Selection Contest", None),
        ("[Unofficial Mirror] 2026 CCPC National Invitational (Nanchang)", None),
        # —— 训练赛后缀不得误杀正赛 ——
        ("The 2021 ICPC Asia Nanjing Regional Contest (XXII Open Cup, Grand Prix of Nanjing)", "regional"),
        ("The 2024 ICPC Asia Hangzhou Regional Contest (The 3rd Universal Cup. Stage 25)", "regional"),
        # —— 站点赛的两种命名 ——
        ("2020 ICPC Shanghai Site", "regional"),
        ("The 2024 ICPC Asia Nanjing Regional Contest", "regional"),
        ("2024 China Collegiate Programming Contest (CCPC) Jinan Site", "regional"),
        ("CCPC 2016-2017, Finals", "regional"),
        ("2016-2017 ACM-ICPC CHINA-Final", "regional"),
        # —— 其余三档 ——
        ("2023 ICPC World Finals", "wf"),
        ("2021 ICPC Asia East Continent Final", "ecfinal"),
        ("2017-2018 ACM-ICPC Asia East Continent League Final (ECL-Final 2017)", "ecfinal"),
        ("The 21st Hunan Provincial Collegiate Programming Contest", "provincial"),
        ("2026 National Invitational of CCPC (Fujian)", "provincial"),
    ]
    for name, want in cases:
        got = icpc.classify(name)
        assert got == want, f"{name!r} 期望 {want}，实得 {got}"


def test_icpc_progress_merge():
    """完成度合并：gym 场没有分母，正式场有；多人取并集且保留各自明细。"""
    from cfhelper import icpc
    contests = [{"id": 900001, "name": "gym 场", "tier": "regional", "gym": True,
                 "year": 2024, "start_ts": 0, "url": ""},
                {"id": 1234, "name": "官方场", "tier": "wf", "gym": False,
                 "year": 2024, "start_ts": 0, "url": ""}]
    saved = list(cf_api.PROBLEMS)
    cf_api.PROBLEMS[:] = [{"key": f"1234_{i}", "contest_id": 1234, "index": i,
                           "name": i, "rating": 2000, "tags": []} for i in "ABCD"]
    try:
        a = {900001: {"solved": ["A", "C"], "tried": ["A", "C"], "names": {}},
             1234:   {"solved": ["A"], "tried": ["A", "B"], "names": {}}}   # B 交过没做出
        b = {900001: {"solved": ["C", "D"], "tried": ["C", "D"], "names": {}}}
        prog = icpc.merge_progress(contests, [("alice", a), ("bob", b)])

        gym = prog[900001]
        assert gym["solved"] == ["A", "C", "D"] and gym["count"] == 3   # 并集去重
        assert gym["total"] is None and gym["pct"] is None              # gym 无题单
        assert gym["by_handle"] == {"alice": ["A", "C"], "bob": ["C", "D"]}
        assert gym["known"] is False                                    # 没题单 -> 只列做过的
        assert [q["i"] for q in gym["problems"]] == ["A", "C", "D"]

        off = prog[1234]
        assert off["total"] == 4 and off["count"] == 1 and off["pct"] == 25   # 官方场有分母
        assert off["tried"] == 1 and off["known"] is True                # B 交过但没做出来
        states = {q["i"]: q["state"] for q in off["problems"]}
        assert states == {"A": "solved", "B": "tried", "C": "none", "D": "none"}
        assert off["problems"][0]["who"] == ["alice"]                    # 谁做出来的
        assert off["problems"][0]["url"].endswith("/contest/1234/problem/A")

        stats = {s["name"]: s for s in icpc.progress_stats(contests, prog)}
        assert stats["区域赛"]["touched"] == 1 and stats["区域赛"]["solved"] == 3
        assert stats["EC-Final"]["touched"] == 0                        # 没碰过的档为 0
    finally:
        cf_api.PROBLEMS[:] = saved


def test_icpc_pick_contest():
    """抽取比赛的三条规则：没解出过的优先、超线的排除、都做过则一视同仁。"""
    from cfhelper import icpc

    def ct(cid, tier="regional"):
        return {"id": cid, "name": f"C{cid}", "tier": tier, "gym": True,
                "year": 2024, "start_ts": 0, "url": ""}

    def pg(count, total, pct):
        return {"solved": [], "count": count, "tried": 0, "total": total,
                "pct": pct, "by_handle": {}, "problems": [], "known": True}

    contests = [ct(1), ct(2), ct(3), ct(4), ct(5), ct(9, "wf")]

    # 1) 有"一题没解出"的场次时，只从它们里面抽（1、2 没有进度记录 -> fresh）
    prog = {3: pg(2, 10, 20), 4: pg(9, 10, 90), 5: pg(6, 10, 60)}
    for _ in range(30):
        picked, info = icpc.pick_contest(contests, prog, tier="regional")
        assert picked["id"] in (1, 2), f"应只从没解出过的里抽，实得 {picked['id']}"
    assert info["source"] == "fresh" and info["fresh"] == 2
    assert info["mastered"] == 1                    # 只有 90% 的那场被排除
    assert info["total"] == 5                       # wf 那场不在本档

    # 2) 恰好 60% 不算超线（要求是"超过 60%"），90% 才排除
    prog_all = {1: pg(1, 10, 10), 2: pg(1, 10, 10), 3: pg(2, 10, 20),
                4: pg(9, 10, 90), 5: pg(6, 10, 60)}
    ids = {icpc.pick_contest(contests, prog_all, "regional")[0]["id"] for _ in range(60)}
    assert 5 in ids, "恰好 60% 不该被排除"
    assert 4 not in ids, "90% 应被排除"

    # 3) 全都做过时一视同仁，源标记为 partial
    _, info = icpc.pick_contest(contests, prog_all, "regional")
    assert info["source"] == "partial" and info["fresh"] == 0 and info["partial"] == 4

    # 4) 交过但一题没解出 -> 仍算没做过
    prog_tried = {1: {"solved": [], "count": 0, "tried": 3, "total": 10, "pct": 0,
                      "by_handle": {}, "problems": [], "known": True}}
    picked, info = icpc.pick_contest(contests, prog_tried, "regional")
    assert info["fresh"] == 5 and picked["id"] in (1, 2, 3, 4, 5)

    # 5) 题单未知（pct=None）算不出比例，不能证明超线 -> 保留
    prog_unknown = {1: pg(1, 10, 10), 2: pg(1, 10, 10), 3: pg(2, 10, 20),
                    4: pg(9, 10, 90),
                    5: {"solved": [], "count": 8, "tried": 0, "total": None,
                        "pct": None, "by_handle": {}, "problems": [], "known": False}}
    ids = {icpc.pick_contest(contests, prog_unknown, "regional")[0]["id"] for _ in range(60)}
    assert 5 in ids, "题单未知的场次不该被当成已吃透而排除"

    # 6) 整档都超线 -> 抽不出来，返回 None 而不是报错
    all_done = {i: pg(9, 10, 90) for i in (1, 2, 3, 4, 5)}
    picked, info = icpc.pick_contest(contests, all_done, "regional")
    assert picked is None and info["mastered"] == 5 and info["pool"] == 0

    # 7) 不限档位时跨档抽取
    picked, info = icpc.pick_contest(contests, {}, tier=None)
    assert info["total"] == 6 and picked is not None


def test_cf_api_signature():
    """CF 签名算法：apiSig = <rand> + sha512(<rand>/<method>?<字典序参数>#<secret>)。

    用固定输入自己算一遍比对，确保参数排序 / 拼接格式没写错——签名错了
    CF 只回一句含糊的 FAILED，很难从现象反推。
    """
    import hashlib
    p = cf_api._sign("contest.standings", {"contestId": 105255, "from": 1, "count": 1},
                     "KEY123", "SECRET456")
    assert p["apiKey"] == "KEY123" and "time" in p
    sig = p.pop("apiSig")
    rand = sig[:6]
    query = "&".join(f"{k}={v}" for k, v in sorted(p.items(), key=lambda kv: (kv[0], str(kv[1]))))
    want = hashlib.sha512(f"{rand}/contest.standings?{query}#SECRET456".encode()).hexdigest()
    assert sig[6:] == want, "签名与手工计算不一致"
    # 参数必须按字典序，apiKey 应排在 contestId 之前
    assert query.index("apiKey") < query.index("contestId") < query.index("count")


def test_icpc_problem_list_states():
    """题单三态：已覆盖 / 没抓过 / 抓过但 CF 不开放。

    第三种必须和第二种分开——否则页面会一直催用户去抓那些永远抓不到的受限赛事。
    """
    from cfhelper import icpc
    from cfhelper.paths import data_path
    orig_file, orig_plist = config.ICPC_PROBLEMS_FILE, icpc._plist
    config.ICPC_PROBLEMS_FILE = "cf_icpc_problems_test.json"
    path = data_path(config.ICPC_PROBLEMS_FILE)
    saved = list(cf_api.PROBLEMS)
    try:
        # 111 用新格式（带题名），444 用旧格式（只有题号）—— 两种都要能读
        icpc._plist = {"111": [["A", "Alpha"], ["B", "Beta"], ["C", "Gamma"]],
                       "222": [],                            # 抓过但 CF 不开放
                       "444": ["A", "B"]}
        cf_api.PROBLEMS[:] = []
        contests = [{"id": 111, "gym": True, "tier": "regional"},
                    {"id": 222, "gym": True, "tier": "regional"},
                    {"id": 333, "gym": True, "tier": "regional"}]
        assert [p["i"] for p in icpc.contest_problems(111)] == ["A", "B", "C"]
        assert icpc.contest_problems(111)[0]["n"] == "Alpha"  # 题名读得出
        assert icpc.contest_problems(222) is None             # 空列表按拿不到处理
        assert icpc.contest_problems(333) is None
        legacy = icpc.contest_problems(444)                   # 旧格式向后兼容
        assert [p["i"] for p in legacy] == ["A", "B"] and legacy[0]["n"] == ""
        st = icpc.problem_fetch_state(contests)
        assert st["covered"] == 1 and st["unavailable"] == 1 and st["missing"] == 1

        # 没配密钥时，全是 gym 的任务不该启动（省掉注定失败的请求）
        if not cf_api.has_api_key():
            assert icpc.fetch_problem_lists(contests) is False
    finally:
        config.ICPC_PROBLEMS_FILE, icpc._plist = orig_file, orig_plist
        cf_api.PROBLEMS[:] = saved
        for p in (path, path + ".tmp", path + ".bad"):
            if os.path.exists(p):
                os.remove(p)


def test_state_changing_endpoints_guarded():
    """改状态的端点必须 POST-only 且拒绝跨站 Origin。

    工具虽然只听 127.0.0.1，但你浏览的任意网页都能往 localhost 发请求：
    以前 <img src="http://127.0.0.1:5000/shutdown"> 就能关掉进程，
    /api/remove_army?handle=x 也能删掉队友。
    """
    from cfhelper import create_app
    client = create_app().test_client()
    changing = ("/shutdown", "/api/add_army?handle=x", "/api/remove_army?handle=x",
                "/api/refresh_army", "/api/todo/remove?key=1_A")
    for url in changing:
        assert client.get(url).status_code == 405, f"{url} 不该接受 GET"
        r = client.post(url, headers={"Origin": "https://evil.example"})
        assert r.status_code == 403, f"{url} 不该接受跨站 Origin"
    # 同源与不带 Origin 的正常调用照旧放行
    for url in ("/api/add_army?handle=", "/api/todo/remove?key=zzz_1"):
        assert client.post(url).status_code == 200
        assert client.post(url, headers={"Origin": "http://localhost"}).status_code == 200
    assert client.get("/heartbeat").status_code == 200      # 只读端点不受影响


def test_user_cache_bounded():
    """回归守护：用户缓存不能只增不减。

    _cache_get 只在读取时判过期、不删条目，subs 又存着完整提交记录，
    不在写入侧回收的话，长时间开着 + 查得多，内存只涨不落。
    """
    saved = dict(cf_api._user_cache)
    cf_api._user_cache.clear()
    try:
        for i in range(config.USER_CACHE_MAX * 3):
            cf_api._cache_put(("subs", f"u{i}"), [i] * 50)
            assert len(cf_api._user_cache) <= config.USER_CACHE_MAX, "缓存超出上限"
        assert cf_api._cache_get(("subs", f"u{config.USER_CACHE_MAX * 3 - 1}")) is not None  # 最新的还在
        assert cf_api._cache_get(("subs", "u0")) is None                                     # 最旧的已淘汰
    finally:
        cf_api._user_cache.clear()
        cf_api._user_cache.update(saved)


def test_shutdown_grace():
    """回归守护：/shutdown 不能让看门狗立刻判超时。

    顶栏跳转等应用内导航也会触发 pagehide 发信标，新页面的第一次心跳要等它加载完才到。
    旧版把 _last_heartbeat 置 0（now - 0 远大于 30），看门狗可能在这个空档里把进程
    杀在跳转途中。现在留 SHUTDOWN_GRACE 秒宽限，任意一次心跳都能取消退出。
    """
    import cfhelper.routes as routes
    would_exit = lambda: time.time() - routes._last_heartbeat > config.HEARTBEAT_TIMEOUT
    saved = routes._last_heartbeat
    try:
        routes._request_shutdown()
        assert not would_exit()                     # 关键：不是立刻超时
        routes._touch()                             # 新页面加载后的心跳
        assert not would_exit()                     # 退出已取消
        routes._request_shutdown()
        routes._last_heartbeat -= config.SHUTDOWN_GRACE + 1     # 宽限期走完
        assert would_exit()                         # 真关页面仍会正常退出
    finally:
        routes._last_heartbeat = saved


def test_render_offline():
    """离线渲染各页（不打网络），守护 base 模板继承与新路由不挂。

    渲染首页会走 contests 的"缓存过期就重建"逻辑；拦掉网络后重建出的是空列表。
    必须把缓存文件改到临时名下，否则会把 0 场比赛写进真实的
    data/cf_upcoming_contests.json，害得之后一小时首页日历全空。
    """
    from cfhelper import create_app
    from cfhelper.paths import data_path
    orig_getter = cf_api.get_contest_list
    orig_files = (config.CONTEST_CACHE_FILE, config.ICPC_CACHE_FILE)
    # 签名要跟真函数一致：ICPC 比赛库会以 gym=True 调用它，只写 lambda: [] 会 TypeError
    cf_api.get_contest_list = lambda gym=False: []
    config.CONTEST_CACHE_FILE = "cf_contests_test.json"
    config.ICPC_CACHE_FILE = "cf_icpc_test.json"
    paths = [data_path(config.CONTEST_CACHE_FILE), data_path(config.ICPC_CACHE_FILE)]
    try:
        client = create_app().test_client()
        for p in ("/", "/picker", "/icpc", "/team", "/vs", "/todo"):
            r = client.get(p)
            assert r.status_code == 200, f"{p} -> {r.status_code}"
            assert "CF 团队助手".encode() in r.data
    finally:
        cf_api.get_contest_list = orig_getter
        config.CONTEST_CACHE_FILE, config.ICPC_CACHE_FILE = orig_files
        for base in paths:
            for p in (base, base + ".tmp", base + ".bad"):
                if os.path.exists(p):
                    os.remove(p)


def run_offline():
    tests = [v for k, v in globals().items() if k.startswith("test_")]
    for t in tests:
        t()
        print(f"  ✅ {t.__name__}")
    print(f"离线测试通过：{len(tests)} 项\n")


def run_net():
    from cfhelper import cf_api, create_app
    print("加载题库缓存...")
    cf_api.load_problem_cache()
    recos = analysis.recommend_problems(1300, 1700, ["dp"], set(), limit=5)
    assert recos and all(1300 <= p["rating"] <= 1700 for p in recos)
    print(f"  ✅ 推荐题目 {len(recos)} 道")

    app = create_app()
    c = app.test_client()
    r = c.post("/", data={"handles": "tourist", "contest_type": "Div.1"})
    assert r.status_code == 200 and "传奇宗师".encode() in r.data
    print("  ✅ 端到端 POST / 渲染成功")
    print("实网测试通过\n")


if __name__ == "__main__":
    print("=== 离线纯函数测试 ===")
    run_offline()
    if "--net" in sys.argv:
        print("=== 实网端到端测试 ===")
        run_net()
    print("全部通过 ✅")
