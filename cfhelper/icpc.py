# -*- coding: utf-8 -*-
"""ICPC 比赛库：从 CF 的 gym + 正式比赛里筛出 ICPC/CCPC 体系赛事，并按级别分四档。

为什么需要"排除规则"
--------------------
CF 的 gym 里混着大量同样带 ICPC 关键词、但并不属于竞赛阶梯的东西，实测踩过的坑：

- `Google Code Jam World Finals` —— 名字里有 "World Finals"，但和 ICPC 无关；
- `2025 Xian Jiaotong University Programming Contest` —— 只是名字带城市的校赛；
- `CT S01E04: ... + Some Problems of 2009 Google Code Jam World Finals` ——
  Codeforces Trainings 把多场比赛拼在一起，名字里能同时命中好几档；
- `Petrozavodsk Camp` / `Opencup` / 独立的 `Universal Cup. Stage N` —— 训练赛系列。

所以先排除、再分档；顺序不能反。

分档口径（从低到高）
--------------------
1. 邀请赛 / 省赛   —— 省级赛、邀请赛、CCPC 网络赛等选拔性质赛事
2. 区域赛         —— ICPC Asia 各站区域赛、CCPC 分站赛与总决赛
3. EC-Final       —— ICPC 亚洲东部大陆决赛
4. World Finals   —— ICPC 全球总决赛
"""
import random
import re
import threading
import time

from . import cf_api, config
from .paths import atomic_write_json, read_json

# ==================== 四档定义 ====================
TIERS = [
    {"key": "provincial", "name": "邀请赛 / 省赛", "cls": "tier-prov", "desc": "省级 / 邀请赛 / 选拔"},
    {"key": "regional",   "name": "区域赛",        "cls": "tier-reg",  "desc": "ICPC Asia 各站 / CCPC 分站与总决赛"},
    {"key": "ecfinal",    "name": "EC-Final",     "cls": "tier-ec",   "desc": "亚洲东部大陆决赛"},
    {"key": "wf",         "name": "World Finals", "cls": "tier-wf",   "desc": "全球总决赛"},
]
TIER_BY_KEY = {t["key"]: t for t in TIERS}

# ==================== 排除：先于分档执行 ====================
# 硬排除：无论名字里还有什么标记，都不属于 ICPC 竞赛阶梯
_EXCLUDE = re.compile(
    r"google\s*code\s*jam|\bgcj\b"              # GCJ 也有 World Finals，与 ICPC 无关
    r"|\bCT\s*S\d+E\d+"                          # Codeforces Trainings 拼盘，会同时命中多档
    r"|freshman|新生|校赛|校内"                    # 校内赛
    r"|team\s*selection|selection\s*contest"     # 选拔赛（如"台大 WF 选拔"，不是 WF 本身）
    r"|warm[-\s]?up"                             # 赛前热身赛，不是正赛
    r"|unofficial\s*mirror"                      # 非官方重制，与正赛重复
    r"|marathon|challenge\s*powered\s*by"        # Huawei 挑战赛等非常规赛制
    , re.I)

# 训练赛系列：只有在"整场就是训练赛"时才排除。
# 真实区域赛常把它作为后缀，例如
#   The 2021 ICPC Asia Nanjing Regional Contest (XXII Open Cup, Grand Prix of ...)
#   The 2024 ICPC Asia Hangzhou Regional Contest (The 3rd Universal Cup. Stage 25: ...)
# 一律排除会误杀这些正赛，所以要求"没有任何阶梯标记"才排除。
_TRAINING_SERIES = re.compile(r"petrozavodsk|open\s*cup|opencup|universal\s*cup", re.I)

# 校赛：出现具体高校名，且没有任何 ICPC/CCPC/省赛标记 —— 只是名字里带了城市而已
_SCHOOL = re.compile(r"university|college of|institute of|\bnormal\b|jiaotong|"
                     r"polytechnic|academy", re.I)
_LADDER_MARK = re.compile(
    r"\bicpc\b|\bacm\b|\bccpc\b|regional|provincial|invitational|world\s*final|"
    r"east\s*continent|ec[-\s]?final|collegiate\s+programming\s+contest", re.I)

# ==================== 分档规则：从高到低，先命中先算 ====================
_RULES = [
    ("wf",         re.compile(r"world\s*final", re.I)),
    ("ecfinal",    re.compile(r"ec[-\s]?final|ecl[-\s]?final|east\s*continent", re.I)),
    # 区域赛：ICPC Asia 各站、CCPC 分站与总决赛、ICPC/CCPC 中国总决赛。
    # 注意站点赛有两种命名：Regional Contest 与 Site（如 "2020 ICPC Shanghai Site"）。
    ("regional",   re.compile(r"regional|"
                              r"\b(icpc|ccpc)\b.*\b(onsite|site)\b|"
                              r"\b(icpc|ccpc)\b.*\bfinals?\b|"          # CCPC Finals / CHINA-Final
                              r"china[-\s]?finals?|"
                              r"\b(asia)\b.*\b(contest|championship)\b", re.I)),
    # 邀请赛 / 省赛：省级、邀请赛、CCPC 网络赛、市级 collegiate
    ("provincial", re.compile(r"provincial|invitational|multi-?provincial|"
                              r"\bccpc\b.*online|online\s*contest|"
                              r"collegiate\s+programming\s+contest", re.I)),
]

# 只保留 ICPC/CCPC 体系（用户选择"中国赛事为主 + WF"，海外区域赛由 CN_ONLY 控制）
_IS_ICPC = re.compile(r"\bicpc\b|\bacm[-\s]?icpc\b|\bccpc\b|world\s*final|"
                      r"east\s*continent|provincial\s+collegiate|invitational", re.I)

# 中国赛事识别：站点城市 + 省份 + 中国专属赛事名
_CN = re.compile(
    r"\bccpc\b|china|chinese|"
    r"nanjing|shanghai|hefei|jinan|shenyang|xi'?an|macau|hong\s?kong|taipei|taichung|"
    r"hangzhou|guangzhou|chengdu|wuhan|harbin|changchun|qingdao|yinchuan|urumqi|"
    r"kunming|nanchang|xuzhou|weihai|shantou|zhuhai|dalian|beijing|shenzhen|chongqing|"
    r"zhengzhou|fuzhou|xiamen|"
    r"jiangsu|guangdong|zhejiang|shandong|henan|hunan|hubei|sichuan|shaanxi|shanxi|"
    r"liaoning|jilin|heilongjiang|anhui|jiangxi|fujian|hebei|yunnan|guizhou|gansu|"
    r"northeast|east\s*continent", re.I)


def classify(name):
    """把比赛名归入四档之一；不属于 ICPC 体系或命中排除规则则返回 None。"""
    if _EXCLUDE.search(name):
        return None
    has_mark = bool(_LADDER_MARK.search(name))
    if _TRAINING_SERIES.search(name) and not has_mark:
        return None                       # 纯训练赛；作为正赛后缀出现时 has_mark 会保住它
    if _SCHOOL.search(name) and not has_mark:
        return None                       # 只是名字带高校/城市的校赛
    if not _IS_ICPC.search(name):
        return None
    for key, pat in _RULES:
        if pat.search(name):
            return key
    return None


def is_chinese(name):
    """是否为中国大陆/港澳台赛事（WF 与 EC-Final 不受此过滤，全球唯一）。"""
    return bool(_CN.search(name))


def _year_of(name, start_ts):
    """优先取名字里的年份（gym 名普遍带年份，比开赛时间更贴合"赛季"）。"""
    m = re.search(r"\b(19|20)\d{2}\b", name)
    if m:
        return int(m.group(0))
    if start_ts:
        return time.gmtime(start_ts).tm_year
    return 0


def _collect(cn_only=True):
    """拉取并筛选比赛。返回按"档位从高到低、年份从新到旧"排好的列表。"""
    gym = cf_api.get_contest_list(gym=True)
    official = cf_api.get_contest_list()
    if gym is None and official is None:
        return None

    out, seen = [], set()
    for src, is_gym in ((official or [], False), (gym or [], True)):
        for c in src:
            name = c.get("name", "")
            tier = classify(name)
            if not tier or c["id"] in seen:
                continue
            # WF / EC-Final 全球唯一，不做中国过滤；其余按需过滤
            if cn_only and tier in ("provincial", "regional") and not is_chinese(name):
                continue
            seen.add(c["id"])
            start = c.get("startTimeSeconds") or 0
            out.append({
                "id":      c["id"],
                "name":    name,
                "tier":    tier,
                "gym":     is_gym,
                "year":    _year_of(name, start),
                "start_ts": start,
                "url":     f"https://codeforces.com/{'gym' if is_gym else 'contest'}/{c['id']}",
            })

    order = {t["key"]: i for i, t in enumerate(TIERS)}
    out.sort(key=lambda c: (-order[c["tier"]], -c["year"], -c["id"]))
    return out


def get_contests(force=False, cn_only=True):
    """带缓存地取 ICPC 比赛库。历史赛事几乎不变，缓存周期比比赛日历长得多。"""
    cache = read_json(config.ICPC_CACHE_FILE)
    if (not force and isinstance(cache, dict)
            and cache.get("cn_only") == cn_only
            and time.time() - cache.get("update_time", 0) < config.ICPC_CACHE_SECONDS):
        return cache.get("contests") or []

    items = _collect(cn_only=cn_only)
    if items is None:                      # 网络失败：宁可用过期缓存，也别给空列表
        return (cache or {}).get("contests") or []
    atomic_write_json(config.ICPC_CACHE_FILE,
                      {"update_time": time.time(), "cn_only": cn_only, "contests": items},
                      indent=None)
    return items


# ==================== 各场题号列表：正式赛来自题库，Gym 需签名抓取 ====================
# 历史比赛的题目组成永不变化，所以这份缓存没有 TTL，抓到就一直用。
_plist = None
_plist_lock = threading.Lock()

# 后台抓取任务状态，供页面轮询进度
_fetch = {"running": False, "done": 0, "total": 0, "ok": 0, "error": ""}


def _load_plist():
    global _plist
    with _plist_lock:
        if _plist is None:
            _plist = read_json(config.ICPC_PROBLEMS_FILE) or {}
        return _plist


def _save_plist():
    with _plist_lock:
        atomic_write_json(config.ICPC_PROBLEMS_FILE, _plist, indent=None)


def contest_problems(contest_id):
    """该场比赛的题目列表 [{i: 题号, n: 题名, r: 难度或 None}, ...]；拿不到返回 None。

    正式比赛用题库缓存（带 rating）；Gym 比赛用签名抓取的缓存（有题名，无 rating）。
    缓存里的空列表是"抓过但 CF 不开放"的标记，同样按拿不到处理。
    """
    official = [{"i": p["index"], "n": p["name"], "r": p["rating"]}
                for p in cf_api.PROBLEMS if p["contest_id"] == contest_id]
    if official:
        return sorted(official, key=lambda p: p["i"])

    raw = _load_plist().get(str(contest_id))
    if not raw:
        return None
    # 兼容两种缓存格式：旧版只存题号列表，新版存 [题号, 题名] 对
    if isinstance(raw[0], str):
        return [{"i": i, "n": "", "r": None} for i in raw]
    return [{"i": x[0], "n": x[1] if len(x) > 1 else "", "r": None} for x in raw]


def problem_fetch_state(contests=None):
    """题单抓取的进度快照，用于页面展示与轮询。

    区分三种状态：已覆盖 / 还没抓过（可以抓）/ 抓过但 CF 不开放（再抓也没用，
    如受限的邀请制赛事）。不区分的话页面会一直催你去抓那些永远抓不到的场次。
    """
    st = dict(_fetch)
    if contests is not None:
        plist = _load_plist()
        covered = missing = unavailable = 0
        for c in contests:
            if contest_problems(c["id"]):
                covered += 1
            elif str(c["id"]) in plist:
                unavailable += 1                 # 抓过，CF 明确不给
            else:
                missing += 1
        st.update(covered=covered, missing=missing, unavailable=unavailable,
                  total_contests=len(contests))
    st["has_key"] = cf_api.has_api_key()
    return st


def fetch_problem_lists(contests, delay=None):
    """后台把缺失的题单逐场抓下来。

    实测串行 1.47s/场、连打不触发限流，157 场约 4 分钟。每 10 场落一次盘，
    这样即使中途关页面导致进程退出，已抓到的部分也不会白费。
    """
    if _fetch["running"]:
        return False
    # 没密钥时 gym 场必然抓不到，但正式赛（匿名可取）仍值得跑一趟
    if not cf_api.has_api_key() and all(c["gym"] for c in contests):
        _fetch["error"] = "未配置 API 密钥"
        return False

    def worker():
        _fetch.update(running=True, done=0, ok=0, error="")
        plist = _load_plist()
        todo_list = [c for c in contests if contest_problems(c["id"]) is None]
        _fetch["total"] = len(todo_list)
        try:
            for i, c in enumerate(todo_list, 1):
                idx = cf_api.get_contest_problem_indices(c["id"], gym=c["gym"])
                # 记空列表表示"抓过但 CF 不开放"，避免每次都把它当成待抓项反复重试
                plist[str(c["id"])] = idx or []
                if idx:
                    _fetch["ok"] += 1
                _fetch["done"] = i
                if i % 10 == 0:
                    _save_plist()                      # 增量落盘，中途退出不丢进度
                time.sleep(delay if delay is not None else config.ICPC_FETCH_DELAY)
            _save_plist()
        except Exception as e:                          # 网络异常不该让线程静默死掉
            _fetch["error"] = str(e)
            _save_plist()
        finally:
            _fetch["running"] = False

    threading.Thread(target=worker, daemon=True).start()
    return True


def merge_progress(contests, members):
    """把多人的做题情况合到每场比赛上。

    members: [(handle, {contestId: {solved, tried, names}}), ...]
    返回 {contestId: {solved: [题号], total: int|None, by_handle: {handle: [题号]}, ...}}
    单人时就是个人视角；多人时 solved 是全队并集，by_handle 保留"谁做出了哪题"。
    """
    out = {}
    for c in contests:
        cid = c["id"]
        union, tried_union, by_handle = set(), set(), {}
        for handle, per in members:
            rec = per.get(cid)
            if not rec:
                continue
            tried_union |= set(rec["tried"])
            if rec["solved"]:
                by_handle[handle] = rec["solved"]
                union |= set(rec["solved"])
        if not union and not tried_union:
            continue
        probs = contest_problems(cid)          # 正式赛来自题库；gym 来自签名抓取的缓存
        total = len(probs) if probs else None  # 仍为 None 表示该场题单还没抓到
        base = "gym" if c["gym"] else "contest"

        # 逐题状态：解出 / 交过但没做出来 / 没碰过。没有题单时退化成只列做过的题。
        rows = probs or [{"i": i, "n": "", "r": None} for i in sorted(union | tried_union)]
        detail = []
        for p in rows:
            idx = p["i"]
            who = [h for h, s in by_handle.items() if idx in s]
            state = "solved" if idx in union else ("tried" if idx in tried_union else "none")
            detail.append({**p, "state": state, "who": who,
                           "url": f"https://codeforces.com/{base}/{cid}/problem/{idx}"})

        out[cid] = {
            "solved":    sorted(union),
            "count":     len(union),
            "tried":     len(tried_union - union),   # 交过但始终没做出来的题数
            "total":     total,                      # None 表示题单未知
            "pct":       round(len(union) / total * 100) if total else None,
            "by_handle": by_handle,
            "problems":  detail,
            "known":     bool(probs),
        }
    return out


def progress_stats(contests, progress):
    """总览：各档参与过的场次与解出题数，用于页面顶部的战绩条。"""
    stats = {t["key"]: {"name": t["name"], "cls": t["cls"], "touched": 0,
                        "total": 0, "solved": 0} for t in TIERS}
    for c in contests:
        s = stats[c["tier"]]
        s["total"] += 1
        p = progress.get(c["id"])
        if p:
            s["touched"] += 1
            s["solved"] += p["count"]
    return [stats[t["key"]] for t in reversed(TIERS)]


def blank_progress(contest):
    """给"一题没做过"的比赛造一份空进度，好让页面照样能列出题目网格。

    merge_progress 只收录有做题记录的场次，但抽取时抽中的多半正是没碰过的——
    没有这份兜底，最常见的情况反而看不到题目列表。
    """
    probs = contest_problems(contest["id"])
    if not probs:
        return None
    base = "gym" if contest["gym"] else "contest"
    return {
        "solved": [], "count": 0, "tried": 0, "total": len(probs), "pct": 0,
        "by_handle": {}, "known": True,
        "problems": [{**p, "state": "none", "who": [],
                      "url": f"https://codeforces.com/{base}/{contest['id']}/problem/{p['i']}"}
                     for p in probs],
    }


def pick_contest(contests, progress, tier=None, skip_rate=None, rng=None):
    """在某一档里抽一场没吃透的比赛来练。返回 (选中的比赛 or None, 统计信息)。

    规则（按用户要求）：
    - **完全没解出过题的场次优先**：只要该档还有这样的场次，就只从它们里面抽；
    - 若该档每场都解出过题，则剩下的一视同仁，等概率抽；
    - **解出比例 > skip_rate 的场次直接排除**——已经吃得差不多了，再练收益低。

    两处边界的取舍：
    - "交过但一题没解出"仍算**没做过**：那场对你依然是完整的练习量；
    - 题单未知的场次（CF 不开放榜单）算不出比例，**不能证明超线**，故保留在池子里。
    """
    rng = rng or random
    skip = config.ICPC_PICK_SKIP_RATE if skip_rate is None else skip_rate
    pool = [c for c in contests if not tier or c["tier"] == tier]

    fresh, partial, mastered = [], [], []
    for c in pool:
        p = progress.get(c["id"])
        if not p or not p["count"]:
            fresh.append(c)                      # 一题没解出 = 完全没做过
        elif p["pct"] is not None and p["pct"] > skip:
            mastered.append(c)                   # 已吃透，排除
        else:
            partial.append(c)

    source = "fresh" if fresh else "partial"
    candidates = fresh or partial
    info = {"tier": tier, "total": len(pool), "fresh": len(fresh),
            "partial": len(partial), "mastered": len(mastered),
            "source": source, "pool": len(candidates), "skip_rate": skip}
    if not candidates:
        return None, info
    return rng.choice(candidates), info


def solved_by_contest(submissions):
    """把某人的提交按 contestId 归拢成 {contestId: {"solved": [题号], "tried": [题号]}}。

    gym 提交同样出现在 user.status 里（已实测），所以历年区域赛做过哪些题能自动对上；
    但 gym 题目在 API 里没有 rating / tags，只有题号与题名。
    """
    by = {}
    for s in submissions or []:
        p = s.get("problem") or {}
        cid, idx = p.get("contestId"), p.get("index")
        if cid is None or not idx:
            continue
        rec = by.setdefault(cid, {"solved": set(), "tried": set(), "names": {}})
        rec["tried"].add(idx)
        rec["names"][idx] = p.get("name", "")
        if s.get("verdict") == "OK":
            rec["solved"].add(idx)
    return {cid: {"solved": sorted(v["solved"]), "tried": sorted(v["tried"]), "names": v["names"]}
            for cid, v in by.items()}
