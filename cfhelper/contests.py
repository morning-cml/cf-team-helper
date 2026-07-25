# -*- coding: utf-8 -*-
"""未来比赛日历：拉取 + 缓存 + 解析等级 + 实时倒计时。

倒计时基于 start_ts 在每次读取时实时计算，因此即使命中 1 小时缓存也不会过期。
"""
import datetime
import time

from . import cf_api, config
from .paths import atomic_write_json, read_json

_CST = datetime.timezone(datetime.timedelta(hours=8))


def _detect_level(name):
    if "Div. 1 + Div. 2" in name:        return "Div.1+Div.2"
    if "Educational" in name:            return "Educational"
    if "Global Round" in name:           return "Global"
    if "Div. 1" in name:                 return "Div.1"
    if "Div. 2" in name:                 return "Div.2"
    if "Div. 3" in name:                 return "Div.3"
    if "Div. 4" in name:                 return "Div.4"
    return "其他"


def _countdown(seconds):
    d = int(seconds // 86400)
    h = int((seconds % 86400) // 3600)
    m = int((seconds % 3600) // 60)
    if d > 0:  return f"{d}天{h}小时"
    if h > 0:  return f"{h}小时{m}分"
    return f"{m}分钟"


def _build_cache():
    """从 CF 拉取未来比赛并写缓存；返回稳定字段列表（不含倒计时）。"""
    raw = cf_api.get_contest_list()
    if raw is None:
        return None
    now    = time.time()
    max_ts = now + config.UPCOMING_DAYS * 86400
    items  = []
    for c in raw:
        if c.get("phase") != "BEFORE":
            continue
        start_ts = c["startTimeSeconds"]
        if start_ts > max_ts:
            continue
        dur = c["durationSeconds"]
        items.append({
            "id":         c["id"],
            "name":       c["name"],
            "level":      _detect_level(c["name"]),
            "start_ts":   start_ts,
            "start_time": datetime.datetime.fromtimestamp(start_ts, tz=_CST).strftime("%Y-%m-%d %H:%M"),
            "duration":   f"{dur // 3600}h{(dur % 3600) // 60:02d}m",
            "url":        f"https://codeforces.com/contest/{c['id']}",
        })
    items.sort(key=lambda x: x["start_ts"])
    atomic_write_json(config.CONTEST_CACHE_FILE,
                      {"update_time": now, "contests": items}, indent=None)
    return items


def get_upcoming_contests():
    items = None
    cache = read_json(config.CONTEST_CACHE_FILE)
    if isinstance(cache, dict) and time.time() - cache.get("update_time", 0) < config.CACHE_EXPIRE_SECONDS:
        items = cache.get("contests")

    if items is None:
        items = _build_cache()
    if not items:
        return []

    # 实时倒计时 + 过滤已开始的比赛
    now, out = time.time(), []
    for c in items:
        cd = c.get("start_ts", 0) - now
        if cd <= 0:
            continue
        item = dict(c)
        item["countdown"]  = _countdown(cd)
        item["level_class"] = config.CONTEST_LEVEL_CLASS.get(c["level"], "lv-other")
        out.append(item)
    return out
