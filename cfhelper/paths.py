# -*- coding: utf-8 -*-
"""路径解析：兼容"源码直接运行"与"PyInstaller 打包 exe"两种模式。

- 资源（templates / static）：打包后位于 _MEIPASS 解包目录。
- 数据（army / 缓存）：必须可写且持久，放在 exe 同级（或源码项目根）的 data/。
"""
import json
import os
import sys


def _is_frozen():
    return getattr(sys, "frozen", False)


def _project_root():
    """源码模式下的项目根目录（cfhelper 的上一级）。"""
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def resource_path(*parts):
    """只读资源路径（打包后从 _MEIPASS 取）。"""
    base = getattr(sys, "_MEIPASS", None) or _project_root()
    return os.path.join(base, *parts)


def _writable_base():
    if _is_frozen():
        return os.path.dirname(sys.executable)
    return _project_root()


DATA_DIR     = os.path.join(_writable_base(), "data")
TEMPLATE_DIR = resource_path("cfhelper", "templates")
STATIC_DIR   = resource_path("cfhelper", "static")


def data_path(name):
    os.makedirs(DATA_DIR, exist_ok=True)
    return os.path.join(DATA_DIR, name)


# ==================== data/ 下 JSON 的安全读写 ====================
def read_json(name, default=None):
    """读 data/ 下的 JSON。

    区分两种"读不到"：文件不存在是正常的（首次运行）→ 直接返回 default；
    文件在却解析不了 = 损坏，此时**必须留痕**——否则调用方拿到空表，下一次保存就把
    损坏文件原地覆盖，用户的大部队 / 题单彻底没了还没有任何提示。这里备份成 .bad 再返回。
    """
    path = data_path(name)
    if not os.path.exists(path):
        return default
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        bad = path + ".bad"
        try:
            os.replace(path, bad)
            hint = f"已备份为 {os.path.basename(bad)}"
        except Exception:
            hint = "备份失败"
        print(f"⚠️ {name} 损坏（{e}），{hint}")
        return default


def atomic_write_json(name, obj, indent=2):
    """原子写 data/ 下的 JSON：先写同目录临时文件，落盘后再 os.replace 覆盖。

    心跳看门狗用 os._exit(0) 硬退出，不做任何清理；若直接以 "w" 覆写原文件、
    恰好停在截断与写完之间，留下的就是残缺 JSON。os.replace 在 Windows / POSIX 上
    都是原子的，任何时刻读到的要么是完整旧内容、要么是完整新内容。
    """
    path = data_path(name)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=indent)
        f.flush()
        os.fsync(f.fileno())        # 确保数据真的落盘，而不是停在系统缓冲里
    os.replace(tmp, path)
