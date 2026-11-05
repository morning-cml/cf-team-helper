# -*- coding: utf-8 -*-
"""比赛涨跌分预测：优先用**实测模型**，没抓过就退回手工校准表。

旧版怎么算的、为什么不够
------------------------
旧版把整场对手都当成同一个 `avg_contest_rating`，再拿手工估的 `ac_to_rank_pct`
把「解出 K 题」映射成名次百分位。两处都是拍脑袋：分区人数、平均分、各档百分位
全是估的，而 Elo 对这些相当敏感。

实测模型换掉了什么
------------------
每种赛制抓几场真实比赛，各存两样东西：

- `hist`：全场选手的**真实 rating 直方图**（来自 contest.ratingChanges）
  —— seed 直接在真实分布上算，不再假设"所有人都是平均分"；
- `k_rank`：**解出 K 题的人实际排在第几名**（standings 的解题数 join ratingChanges 的名次）
  —— 不再需要猜百分位。

两份数据必须来自**同一场**比赛，名次才对得上尺度；所以模型按"场"存，
预测时逐场算一遍再平均，而不是把不同场次的直方图拌在一起（人数一混，名次尺度就废了）。

名次为什么取 ratingChanges 的
----------------------------
实测同一场 Div.2：standings 只有 8620 行，ratingChanges 却有 12494 人。
涨分算法用的是后者的名次空间（拿它回归误差中位数为 0），所以 K→名次 也必须落在那个空间里，
靠 handle 把两边 join 起来，**只统计两边都能对上的那部分人**。

多出来的三千多人别乱猜。他们以首次参赛者和低分号为主（1304 个首次参赛者一个不落全在里面），
但名次从第 1 名到垫底都有——最初想当然地把他们算成"解出 0 题"，
直接算出了「解 1 题比解 0 题名次还差」这种一眼假的结果。

代价（实测）
------------
一场 = ratingChanges 约 2MB/5 秒 + standings 约 6.5MB/10 秒。
7 种赛制 × 2 场 = 14 场，实测 **160 秒**跑完、14/14 全部成功，模型文件 **218 KB**。
一次性开销，之后永久缓存；模型通用，可以随 Release 分发给队友。
"""
import statistics
import threading
import time

from . import analysis, cf_api, config, contests, rating
from .paths import atomic_write_json, read_json

MODEL_VERSION = 1

# contests.detect_level 的标签 → 预测下拉框里的赛制名
_LEVEL_TO_TYPE = {
    "Div.4": "Div.4", "Div.3": "Div.3", "Div.2": "Div.2", "Div.1": "Div.1",
    "Div.1+Div.2": "Div.1+Div.2",
    "Educational": "Educational Round", "Global": "Global Round",
}

_model = None
_lock = threading.Lock()

# 后台抓取状态，供页面轮询
_fetch = {"running": False, "done": 0, "total": 0, "ok": 0, "error": "", "current": ""}


def detect_type(name):
    """比赛名 → 赛制。识别不出返回 None。

    直接复用比赛日历的判定，两处口径必须一致：否则日历说这是 Educational、
    预测模型却把它归到 Div.2，用户看到的两个数就对不上了。
    """
    return _LEVEL_TO_TYPE.get(contests.detect_level(name))


# ==================== 模型读写 ====================
def load_model():
    """读模型缓存（进程内只读一次）。没有返回 {}。"""
    global _model
    with _lock:
        if _model is None:
            cache = read_json(config.PREDICT_MODEL_FILE)
            if isinstance(cache, dict) and cache.get("version") == MODEL_VERSION:
                _model = cache.get("types") or {}
            else:
                _model = {}       # 没有 / 旧版本格式，当没抓过处理
        return _model


def _save_model(types):
    atomic_write_json(config.PREDICT_MODEL_FILE,
                      {"version": MODEL_VERSION, "update_time": time.time(), "types": types},
                      indent=None)


def model_state():
    """给页面看的模型状态：哪些赛制有实测数据、基于哪几场。"""
    m = load_model()
    st = dict(_fetch)
    st["types"] = {t: [{"id": s["id"], "name": s["name"], "n": s["n"],
                        "problems": s["problems"]} for s in m.get(t, [])]
                   for t in config.CONTEST_TYPES}
    st["covered"] = sum(1 for t in config.CONTEST_TYPES if m.get(t))
    # 别用 "total"：那是 _fetch 里的抓取场次总数，前端进度条靠它算百分比
    st["types_total"] = len(config.CONTEST_TYPES)
    st["samples_per_type"] = config.PREDICT_SAMPLES
    return st


# ==================== 建模 ====================
def _solved_count(row):
    """一行榜单里解出了几题。

    CF 赛制记分不是解题数（分数随时间衰减），所以要数"得分为正的题"；
    ICPC 赛制下 points 才直接等于解题数。数 problemResults 对两者都成立。
    """
    return sum(1 for p in row.get("problemResults") or [] if (p.get("points") or 0) > 0)


def _monotonic_k_rank(ranks_by_k):
    """{解题数: [名次...]} → {解题数: 中位名次}，并强制"多解一题名次必须更靠前"。

    样本太少的档直接丢掉——比如某场只有 2 个人解出满题，他们的中位名次代表不了
    "解出满题大概排第几"。剩下的按解题数升序扫，名次没有严格变小的档同样丢掉：
    那说明这一档的数据有问题，宁可少给一行，也不能在表格里出现
    "解 1 题比解 0 题还惨"这种一眼假的结果。
    """
    med = {k: int(statistics.median(v)) for k, v in ranks_by_k.items()
           if len(v) >= config.PREDICT_MIN_SAMPLES_PER_K}
    out, last = {}, None
    for k in sorted(med):
        if last is None or med[k] < last:
            out[str(k)] = med[k]
            last = med[k]
    return out


def build_sample(contest_id, name="", start_ts=0):
    """把一场真实比赛压成模型样本。任一份数据拿不到就返回 None。"""
    changes = cf_api.get_rating_changes(contest_id)
    if not changes:
        return None                     # 未评级 / 拿不到，这场不能用
    standings = cf_api.get_standings(contest_id)
    if not standings:
        return None

    hist = {}
    rank_of = {}
    for c in changes:
        r = c.get("oldRating") or 0
        r = r if r > 0 else config.UNRATED_IN_FIELD    # 首次参赛者折算，见 config 注释
        hist[r] = hist.get(r, 0) + 1
        rank_of[c["handle"]] = c["rank"]

    # 解出 K 题的人，实际落在 ratingChanges 名次空间的第几名。
    # 只统计**两边都能对上**的人：榜单缺了约三成选手（实测一场 Div.2 榜单 8620 行、
    # 涨分记录 12494 人），缺的那批以首次参赛者和低分号为主，且名次从第 1 名到垫底都有——
    # 早先想当然地把"只在涨分记录里"的人算成 0 题，直接算出了"解 1 题比解 0 题名次还差"。
    ranks_by_k = {}
    for row in standings["rows"]:
        members = (row.get("party") or {}).get("members") or []
        if len(members) != 1:
            continue                    # 队伍行不参与个人预测
        rk = rank_of.get(members[0].get("handle"))
        if rk is None:
            continue                    # 没受评（场外 / 虚拟参赛），不在算法的名次空间里
        ranks_by_k.setdefault(_solved_count(row), []).append(rk)

    k_rank = _monotonic_k_rank(ranks_by_k)
    if not k_rank:
        return None
    return {
        "id": contest_id,
        "name": name or standings["contest"].get("name", ""),
        "start_ts": start_ts or standings["contest"].get("startTimeSeconds") or 0,
        "n": len(changes),
        "problems": len(standings["problems"]),
        "hist": {str(k): v for k, v in sorted(hist.items())},
        "k_rank": k_rank,
    }


def _pick_contests(per_type):
    """给每种赛制挑最近 per_type 场已结束的比赛。拿不到比赛列表返回 None。"""
    raw = cf_api.get_contest_list()
    if raw is None:
        return None
    done = [c for c in raw if c.get("phase") == "FINISHED" and c.get("startTimeSeconds")]
    done.sort(key=lambda c: -c["startTimeSeconds"])
    out, have = [], {t: 0 for t in config.CONTEST_TYPES}
    for c in done:
        t = detect_type(c.get("name", ""))
        if not t or have[t] >= per_type:
            continue
        have[t] += 1
        out.append((t, c["id"], c["name"], c["startTimeSeconds"]))
    return out


def fetch_model(per_type=None, delay=None):
    """后台重建预测模型。已在跑则返回 False。

    整场重建而不是增量：赛制的人数与难度会随季度漂移，混着新旧样本反而不好解释。
    单场失败（未评级 / 榜单不开放）直接跳过，不影响其它赛制。
    """
    if _fetch["running"]:
        return False
    per_type = per_type or config.PREDICT_SAMPLES

    def worker():
        global _model
        _fetch.update(running=True, error="", done=0, ok=0, total=0, current="")
        try:
            picked = _pick_contests(per_type)
            if picked is None:
                _fetch["error"] = "拉取比赛列表失败"
                return
            _fetch["total"] = len(picked)
            types = {}
            for i, (t, cid, name, ts) in enumerate(picked, 1):
                _fetch["current"] = f"{t} · {name[:40]}"
                sample = build_sample(cid, name, ts)
                if sample:
                    types.setdefault(t, []).append(sample)
                    _fetch["ok"] += 1
                _fetch["done"] = i
                time.sleep(delay if delay is not None else config.PREDICT_FETCH_DELAY)
            if types:
                _save_model(types)
                with _lock:
                    _model = types
                    _fields.clear()       # 换了样本，缓存的 Field 必须作废
        except Exception as e:                # 后台线程别静默死掉
            _fetch["error"] = str(e)
        finally:
            _fetch.update(running=False, current="")

    threading.Thread(target=worker, daemon=True).start()
    return True


# ==================== 预测 ====================
_fields = {}


def _fields_for(contest_type, samples):
    """按赛制缓存 Field 对象。

    Field 里的 seed 记忆化是这里的关键：seed(r) **只跟场次的 rating 分布有关，
    跟查询者是谁无关**，所以跨请求完全可以复用。每次重建的话，一次预测要重算
    五百多万次乘加——实测首次 346 毫秒，复用后几乎为零。
    """
    hit = _fields.get(contest_type)
    if hit and len(hit) == len(samples) and all(
            f_s["id"] == s["id"] for (f_s, _), s in zip(hit, samples)):
        return hit
    built = [(s, rating.Field(s["hist"])) for s in samples]
    _fields[contest_type] = built
    return built


def _row(rank, n, delta, perf, user_rating):
    new_r = max(0, user_rating + delta)
    return {
        "rank": int(rank),
        "rank_pct": round(rank / n * 100, 1) if n else 0,
        "performance": int(perf),
        "rating_change": int(delta),
        "new_rating": new_r,
        "rank_info": analysis.get_rank_info(new_r),
    }


def predict(user_rating, contest_type):
    """返回 {解题数: {rank, rank_pct, performance, rating_change, new_rating, rank_info}}。

    有实测模型就逐场算再平均；没有就退回 analysis.generate_prediction 的手工校准表。
    第二个返回值是"这次是怎么算出来的"，给模板显示依据。
    """
    samples = load_model().get(contest_type) or []
    if not samples:
        return analysis.generate_prediction(user_rating, contest_type), {
            "measured": False,
            "note": "尚未抓取真实比赛数据，当前为手工校准的估算值",
            "samples": [],
        }

    user_rating = int(user_rating)
    fields = _fields_for(contest_type, samples)
    ks = sorted({int(k) for s in samples for k in s["k_rank"]})

    out = {}
    for k in ks:
        rows = []
        for s, field in fields:
            rk = s["k_rank"].get(str(k))
            if rk is None:
                continue
            rows.append((rk, s["n"], field.delta(rk, user_rating), field.performance(rk)))
        if not rows:
            continue
        out[k] = _row(
            statistics.mean(r[0] for r in rows),
            statistics.mean(r[1] for r in rows),
            round(statistics.mean(r[2] for r in rows)),
            round(statistics.mean(r[3] for r in rows)),
            user_rating,
        )
    if not out:
        return analysis.generate_prediction(user_rating, contest_type), {
            "measured": False, "note": "实测模型里没有这种赛制的数据", "samples": []}
    return out, {
        "measured": True,
        "note": f"基于 {len(samples)} 场真实比赛的完整榜单与涨分记录",
        "samples": [{"name": s["name"], "n": s["n"], "problems": s["problems"]}
                    for s in samples],
    }
