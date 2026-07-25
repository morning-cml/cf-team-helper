# -*- coding: utf-8 -*-
"""CF 辅助工具 —— 应用工厂。"""
import threading

from flask import Flask

from . import army, cf_api, config, paths, routes

__version__ = config.APP_VERSION


def create_app():
    app = Flask(
        __name__,
        template_folder=paths.TEMPLATE_DIR,
        static_folder=paths.STATIC_DIR,
        static_url_path="/static",
    )
    routes.register(app)
    return app


def start_background(refresh_army=True):
    """后台预热：加载题库缓存 + 刷新大部队，不阻塞首屏。"""
    def worker():
        cf_api.load_problem_cache()
        if refresh_army:
            ok, total = army.refresh_army()
            if total:
                print(f"✅ 大部队刷新完成：{ok}/{total}")
    threading.Thread(target=worker, daemon=True).start()
