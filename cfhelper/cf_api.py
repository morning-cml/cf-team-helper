# -*- coding: utf-8 -*-
"""Codeforces API 封装层。

职责：所有对外 HTTP 请求都集中在这里，统一超时 / 轻量重试 / 异常处理，
对上层只暴露"干净的数据结构或 None / []"。

性能：
- 全局信号量把同时在飞的请求压到 HTTP_MAX_CONCURRENCY，既能并行加速又不触发 CF 限流；
- info / status / rating 三类用户数据带进程内 TTL 缓存，重复查询 / army 点详情直接命中。
"""
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import requests

from . import config

# CF 用户名合法字符：字母/数字/下划线/连字符/点，长度 1-24。
# 提前挡掉空格、引号、逗号残留等垃圾输入，省掉注定失败的网络请求，错误也更清晰。
_HANDLE_RE = re.compile(r"^[A-Za-z0-9_.-]{1,24}$")


def is_valid_handle(handle):
    return bool(handle and _HANDLE_RE.match(handle))

# ==================== 题库难度缓存（进程级，只加载一次） ====================
# PROBLEM_RATING: "contestId_index" -> rating，供 O(1) 难度查询
# PROBLEMS:       带 rating 的题目列表，供"推荐题目 / 刷题器"功能筛选
PROBLEM_RATING = {}
PROBLEMS = []
_problem_loaded = False
_problem_lock = threading.Lock()

# 全局并发闸门：无论从哪里发起请求，同时在飞的 CF 请求都不超过这个数
_throttle = threading.Semaphore(config.HTTP_MAX_CONCURRENCY)

# 用户数据 TTL 缓存： (kind, handle_lower) -> (ts, value)
_user_cache = {}
_user_cache_lock = threading.Lock()


def _cache_get(key):
    with _user_cache_lock:
        hit = _user_cache.get(key)
    if hit and time.time() - hit[0] < config.USER_CACHE_TTL:
        return hit[1]
    return None


def _cache_put(key, value):
    """写缓存，并把容量压在 USER_CACHE_MAX 内。

    _cache_get 只在读取时判过期、不删条目，所以必须在写入侧回收：
    先清掉已过期的，仍超限就淘汰最旧的（subs 条目动辄上万条提交，放任不管内存只涨不落）。
    """
    now = time.time()
    with _user_cache_lock:
        _user_cache[key] = (now, value)
        if len(_user_cache) <= config.USER_CACHE_MAX:
            return
        for k in [k for k, (ts, _) in _user_cache.items()
                  if now - ts >= config.USER_CACHE_TTL]:
            del _user_cache[k]
        while len(_user_cache) > config.USER_CACHE_MAX:
            del _user_cache[min(_user_cache, key=lambda k: _user_cache[k][0])]


def _get(url, params=None):
    """带重试的 GET，返回 CF 标准响应里的 dict（status==OK）或 None。

    - 信号量限流：只在真正发请求时占用名额，sleep/解析不占；
    - 触发 CF 限流（comment 含 limit）会退避重试，业务错误（用户不存在）则立即返回 None。
    """
    last_err = None
    for attempt in range(config.HTTP_RETRY + 1):
        try:
            with _throttle:
                res = requests.get(url, params=params, timeout=config.HTTP_TIMEOUT)
            data = res.json()
            if data.get("status") == "OK":
                return data
            comment = (data.get("comment") or "").lower()
            if "limit" in comment:          # CF 限流 → 退避后重试
                last_err = f"CF 限流: {comment}"
                if attempt < config.HTTP_RETRY:
                    time.sleep(1.0 * (attempt + 1))
                    continue
            return None                      # 业务错误（用户不存在等）不重试
        except Exception as e:               # 网络/解析异常 → 重试
            last_err = e
            if attempt < config.HTTP_RETRY:
                time.sleep(0.6 * (attempt + 1))
    if last_err:
        print(f"⚠️ 请求失败 {url} : {last_err}")
    return None


# ==================== 用户基础信息 ====================
def get_user_info(handle, force=False):
    """返回用户基础信息 dict；用户不存在 / 请求失败返回 None。force=True 跳过缓存。"""
    ck = ("info", handle.lower())
    if not force:
        cached = _cache_get(ck)
        if cached is not None:
            return cached
    data = _get(config.CF_INFO_API, {"handles": handle})
    if not data or not data["result"]:
        return None
    u = data["result"][0]
    rating = u.get("rating", 0)
    if   rating >= 2400: medal = "gold"
    elif rating >= 2100: medal = "silver"
    elif rating >= 1900: medal = "bronze"
    else:                medal = ""
    info = {
        "handle":      u["handle"],
        "rating":      rating,
        "max_rating":  u.get("maxRating", 0),
        "rank":        u.get("rank", "unrated"),
        "medal_class": medal,
        "avatar":      u.get("titlePhoto", ""),
    }
    _cache_put(ck, info)
    return info


# ==================== 提交记录（一次拉取，多处复用） ====================
def get_submissions(handle):
    """拉取用户全部提交（user.status）。失败返回 None，无记录返回 []。"""
    ck = ("subs", handle.lower())
    cached = _cache_get(ck)
    if cached is not None:
        return cached
    data = _get(config.CF_STATUS_API, {"handle": handle})
    if data is None:
        return None
    result = data["result"]
    _cache_put(ck, result)
    return result


# ==================== Rating / 比赛历史（修正端点：user.rating） ====================
def get_rating_history(handle):
    """返回按时间升序的比赛 Rating 变化列表；失败返回 []。

    旧版误用 user.contests（不存在的端点）导致"最近比赛"永远为空，这里修正为
    官方的 user.rating，字段为 contestName / rank / oldRating / newRating。
    """
    ck = ("rating", handle.lower())
    cached = _cache_get(ck)
    if cached is not None:
        return cached
    data = _get(config.CF_RATING_API, {"handle": handle})
    if not data:
        return []                            # 失败不缓存，留给下次恢复
    out = []
    for c in data["result"]:
        out.append({
            "contest_id":    c.get("contestId"),
            "name":          c.get("contestName", ""),
            "rank":          c.get("rank", 0),
            "old_rating":    c.get("oldRating", 0),
            "new_rating":    c.get("newRating", 0),
            "rating_change": c.get("newRating", 0) - c.get("oldRating", 0),
            "time":          c.get("ratingUpdateTimeSeconds", 0),
        })
    _cache_put(ck, out)
    return out


def fetch_user_bundle(handle):
    """并行拉取单个用户的 info / submissions / rating，返回三元组。

    单用户查询时把原本串行的 3 个海外请求并行化，配合全局信号量自动限流。
    """
    with ThreadPoolExecutor(max_workers=3) as ex:
        f_info = ex.submit(get_user_info, handle)
        f_subs = ex.submit(get_submissions, handle)
        f_rate = ex.submit(get_rating_history, handle)
        return f_info.result(), f_subs.result(), f_rate.result()


# ==================== 比赛列表（未来比赛日历用） ====================
def get_contest_list():
    """返回 contest.list 原始结果列表；失败返回 None。"""
    data = _get(config.CF_CONTESTS_API)
    if data is None:
        return None
    return data["result"]


# ==================== 题库难度 / 标签缓存 ====================
def load_problem_cache(force=False):
    """加载全站题目的 rating 与 tags。线程安全，重复调用直接返回。"""
    global _problem_loaded
    with _problem_lock:
        if _problem_loaded and not force:
            return
        data = _get(config.CF_PROBLEM_API)
        if not data:
            print("⚠️ 题库缓存加载失败，难度分级 / 推荐 / 刷题器功能将降级")
            return
        PROBLEM_RATING.clear()
        PROBLEMS.clear()
        for p in data["result"]["problems"]:
            if "rating" not in p:
                continue
            key = f"{p['contestId']}_{p['index']}"
            PROBLEM_RATING[key] = p["rating"]
            PROBLEMS.append({
                "key":        key,
                "contest_id": p["contestId"],
                "index":      p["index"],
                "name":       p.get("name", ""),
                "rating":     p["rating"],
                "tags":       p.get("tags", []),
            })
        _problem_loaded = True
        print(f"✅ 题库缓存完成：{len(PROBLEM_RATING)} 题带难度分")


def problem_rating(key, default=0):
    return PROBLEM_RATING.get(key, default)


def all_tags():
    """题库里出现过的全部标签（升序），供刷题器下拉选择。"""
    s = set()
    for p in PROBLEMS:
        s.update(p["tags"])
    return sorted(s)
