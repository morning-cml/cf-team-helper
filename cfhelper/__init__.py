# -*- coding: utf-8 -*-
#
# CF 团队助手 —— Codeforces 团队辅助工具
# Copyright (C) 2026 morning-cml <https://github.com/morning-cml>
#
# 本程序是自由软件：你可以依据 GNU 通用公共许可证 v3（或任你选择的更新版本）
# 的条款再分发和/或修改它。分发修改版时必须同样开源、保留本声明并标注改动。
# 本程序不附带任何担保。许可证全文见随附的 LICENSE，或 <https://www.gnu.org/licenses/>。
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
