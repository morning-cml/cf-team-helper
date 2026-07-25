# -*- coding: utf-8 -*-
"""启动入口：python run.py（源码运行 / 打包后的 exe 同样调用 main）。"""
import os
import sys
import threading
import time
import webbrowser

from cfhelper import __version__, create_app, routes, start_background

HOST = "127.0.0.1"
PORT = 5000


def _safe_console():
    """让含 emoji 的日志在 GBK 控制台 / 管道重定向下也不崩。

    --noconsole 打包后 stdout/stderr 为 None，werkzeug 等库直接写会异常，先接到 devnull。
    """
    if sys.stdout is None or sys.stderr is None:
        null = open(os.devnull, "w", encoding="utf-8")
        sys.stdout = sys.stdout or null
        sys.stderr = sys.stderr or null

    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="backslashreplace")
        except Exception:
            pass


def _open_browser():
    time.sleep(1.5)
    webbrowser.open(f"http://{HOST}:{PORT}")


def main():
    _safe_console()
    print("=" * 55)
    print(f"🚀  CF 辅助工具 v{__version__} 启动中...")
    print("=" * 55)

    app = create_app()
    start_background(refresh_army=True)        # 后台预热题库 + 刷新大部队
    routes.start_heartbeat_watcher()           # 页面关闭 → 进程退出
    threading.Thread(target=_open_browser, daemon=True).start()

    print(f"🌐  访问地址: http://{HOST}:{PORT}")
    print("💡  关闭浏览器页面后程序将自动退出")
    print("=" * 55)
    app.run(host=HOST, port=PORT, debug=False, use_reloader=False)


if __name__ == "__main__":
    main()
