# 修改历史 (Revision History)
# ==================================
# 版本: v1.1.0
# 日期: 2026-06-16
# 修改说明: 挂载前端打包静态资产目录，并配置 SPA Catchall Fallback 逻辑以支持客户端路由无缝刷新。
# ----------------------------------
# 版本: v1.0.0
# 日期: 2026-06-15
# 修改说明: 实现 FastAPI 应用创建工厂，并挂载跨域 CORS 中间件与 API 路由器。
# ==================================

# -*- coding: utf-8 -*-
from pathlib import Path
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from api_probe_system.web.routes import platforms, reports, tests

def create_app() -> FastAPI:
    app = FastAPI(
        title="API Probe Station Backend",
        description="API 平台智能探测系统 Web API 后端层",
        version="1.1.0"
    )

    # 跨域配置 (CORS) — 支持前端开发服务器（如 5173 端口）跨域调用
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],  # 开发阶段放开限制，未来可限制为特定前端源
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # 挂载路由
    app.include_router(platforms.router, prefix="/api")
    app.include_router(reports.router, prefix="/api")
    app.include_router(tests.router, prefix="/api")

    @app.get("/health")
    async def health_check():
        return {"status": "ok", "message": "API Probe Station 后端运行正常"}

    # 挂载前端打包文件静态目录 (如果已 build 生成)
    frontend_dist = Path(__file__).resolve().parent.parent / "frontend" / "dist"
    if frontend_dist.exists():
        app.mount("/", StaticFiles(directory=str(frontend_dist), html=True), name="static")
        
        # HTML Fallback: 用于处理 SPA 路由刷新导致 404 的问题
        # 对任何无法匹配到 API 和静态文件的 GET 请求，返回 index.html
        @app.get("/{catchall:path}")
        async def read_index(catchall: str):
            index_path = frontend_dist / "index.html"
            if index_path.exists():
                return FileResponse(index_path)
            return {"status": "error", "message": "Static assets built but index.html missing"}

    return app
