# -*- coding: utf-8 -*-
"""大部队（关注队友）管理：增删、去重、批量刷新 Rating。"""
import threading
from concurrent.futures import ThreadPoolExecutor

from . import cf_api, config
from .analysis import get_rank_info
from .paths import atomic_write_json, read_json

# 串行化所有"读-改-写"操作，防止并发（刷新 + 增删）交错写坏 JSON 文件。
# 注意：load_army / save_army 自身不加锁，由公开操作持锁后调用，避免锁重入死锁。
_army_lock = threading.Lock()


def _member_from_info(info):
    ri = get_rank_info(info["rating"])
    return {
        "handle":      info["handle"],
        "rating":      info["rating"],
        "max_rating":  info["max_rating"],
        "rank_name":   ri["current_name"],
        "rank_color":  ri["current_color"],
        "medal_class": info["medal_class"],
    }


def load_army():
    return read_json(config.ARMY_FILE, []) or []


def save_army(members):
    seen, unique = set(), []
    for m in members:
        if m["handle"] not in seen:
            seen.add(m["handle"])
            unique.append(m)
    atomic_write_json(config.ARMY_FILE, unique)      # 原子写，避免硬退出撞出残缺文件


def add_to_army(handle):
    if not cf_api.is_valid_handle(handle):
        return False, "用户名格式非法"
    info = cf_api.get_user_info(handle)          # 网络请求放锁外
    if not info:
        return False, "用户不存在或 API 请求失败"
    with _army_lock:
        army = load_army()
        if any(m["handle"].lower() == handle.lower() for m in army):
            return False, "该用户已在大部队中"
        army.append(_member_from_info(info))
        save_army(army)
    return True, f"已将 {info['handle']} 加入大部队"


def remove_from_army(handle):
    with _army_lock:
        army = load_army()
        new = [m for m in army if m["handle"].lower() != handle.lower()]
        if len(new) == len(army):
            return False, "该用户不在大部队中"
        save_army(new)
    return True, "已移出大部队"


def refresh_army():
    """重新拉取所有成员的最新 Rating；返回 (成功数, 总数)。

    并行拉取（受全局信号量限流），force=True 跳过缓存确保拿到最新分数；
    ex.map 保序，刷新失败的成员保留旧数据。
    """
    with _army_lock:
        army = load_army()
    if not army:
        return 0, 0
    workers = min(len(army), config.HTTP_MAX_CONCURRENCY)
    with ThreadPoolExecutor(max_workers=workers) as ex:    # 网络拉取放锁外，不阻塞渲染读
        infos = list(ex.map(lambda m: cf_api.get_user_info(m["handle"], force=True), army))

    fresh = {m["handle"].lower(): _member_from_info(info)
             for m, info in zip(army, infos) if info}
    with _army_lock:
        # 重新读一次再合并：网络拉取那几秒里用户可能已增删过成员，
        # 直接写回开头那份快照会把这些改动冲掉（刷新失败的成员自然保留旧数据）。
        current = load_army()
        save_army([fresh.get(m["handle"].lower(), m) for m in current])
    return len(fresh), len(army)
