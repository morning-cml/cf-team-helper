# -*- coding: utf-8 -*-
"""题单 / 待做收藏：本地持久化（data/cf_todo.json），跨会话保留。

题目以 key（contestId_index）唯一去重；URL 由 key 重建，不信任前端传入的链接，
避免存进 javascript: 之类的恶意 URL。增删改用锁串行化，防并发写坏文件。
"""
import threading
import time

from . import config
from .paths import atomic_write_json, read_json

_lock = threading.Lock()


def _url_of(key):
    cid, _, idx = key.partition("_")
    return f"https://codeforces.com/problemset/problem/{cid}/{idx}"


def valid_key(key):
    cid, sep, idx = key.partition("_")
    return bool(sep and cid.isdigit() and idx)


def load():
    return read_json(config.TODO_FILE, []) or []


def _save(items):
    atomic_write_json(config.TODO_FILE, items)       # 原子写，避免硬退出撞出残缺文件


def add(key, name, rating=0, tags=None):
    if not valid_key(key) or not name:
        return False, "题目信息不完整或 key 非法"
    item = {"key": key, "name": name, "rating": rating, "tags": tags or [],
            "url": _url_of(key), "done": False, "added_ts": time.time()}
    with _lock:
        items = load()
        if any(i["key"] == key for i in items):
            return False, "该题已在题单中"
        items.append(item)
        _save(items)
    return True, f"已加入题单：{name}"


def remove(key):
    with _lock:
        items = load()
        new = [i for i in items if i["key"] != key]
        if len(new) == len(items):
            return False, "题目不在题单中"
        _save(new)
    return True, "已从题单移除"


def toggle(key):
    with _lock:
        items = load()
        hit = False
        for i in items:
            if i["key"] == key:
                i["done"] = not i.get("done", False)
                hit = True
        if not hit:
            return False, "题目不在题单中"
        _save(items)
    return True, "状态已更新"


def clear_done():
    with _lock:
        items = load()
        kept = [i for i in items if not i.get("done")]
        _save(kept)
    return len(items) - len(kept)
