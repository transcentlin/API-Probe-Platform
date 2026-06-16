# 修改历史 (Revision History)
# ==================================
# 版本: v1.1.1
# 日期: 2026-06-16
# 修改说明: 对获取探测历史日志（GET /history）增加基于 st_mtime 的 _HISTORY_CACHE 内存缓存机制，大幅降低高频轮询（每3秒）下的磁盘 I/O 及 JSON 序列化压力。
# ----------------------------------
# 版本: v1.1.0
# 日期: 2026-06-16
# 修改说明: 挂载 /history 路由支持历史探测日志的读取与一键清理。
# ----------------------------------
# 版本: v1.0.0
# 日期: 2026-06-15
# 修改说明: 实现异步探测启动和 Server-Sent Events (SSE) 进度实时推送接口。
# ==================================

# -*- coding: utf-8 -*-
import json
import asyncio
from pathlib import Path
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from api_probe_system.web.dependencies import get_platform_manager, get_config_manager
from api_probe_system.web.schemas import TestStartRequest
from api_probe_system.web.test_runner import web_test_runner
from api_probe_system.core.platform_manager import PlatformManager

router = APIRouter(prefix="/tests", tags=["Tests"])

@router.post("/start")
async def start_tests(
    data: TestStartRequest,
    pm: PlatformManager = Depends(get_platform_manager),
    config_mgr = Depends(get_config_manager)
):
    """启动指定平台列表的探测测试（异步后台任务）。"""
    started = []
    already_running = []
    invalid_platforms = []

    # 验证平台是否存在
    existing_platforms = {p.name for p in pm.list_platforms(include_disabled=True)}

    for name in data.platforms:
        if name not in existing_platforms:
            invalid_platforms.append(name)
            continue

        # 启动测试
        success = web_test_runner.start_test(name, data.mode, pm, config_mgr)
        if success:
            started.append(name)
        else:
            already_running.append(name)

    if not started and already_running:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"请求的平台已在进行测试中: {', '.join(already_running)}"
        )
    elif not started and invalid_platforms:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"未找到指定的平台: {', '.join(invalid_platforms)}"
        )

    return {
        "message": f"成功拉起 {len(started)} 个平台的异步探测任务",
        "started": started,
        "already_running": already_running,
        "invalid_platforms": invalid_platforms
    }

@router.get("/events")
async def get_test_events():
    """SSE (Server-Sent Events) 实推送端点。"""
    q = web_test_runner.publisher.subscribe()

    async def event_generator():
        try:
            while True:
                try:
                    # 每 15 秒如果无事件则触发超时发送心跳
                    data = await asyncio.wait_for(q.get(), timeout=15.0)
                    yield f"data: {json.dumps(data, ensure_ascii=False)}\n\n"
                except asyncio.TimeoutError:
                    # 发送空的心跳包保持连接
                    yield ": ping\n\n"
        except asyncio.CancelledError:
            # 客户端断开连接时注销订阅队列，避免内存泄漏
            web_test_runner.publisher.unsubscribe(q)
            raise

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"  # 禁用 Nginx 缓存缓冲以确保即时发送
        }
    )

_HISTORY_CACHE: dict = {"mtime": 0.0, "data": []}

@router.get("/history")
async def get_test_history(config_mgr = Depends(get_config_manager)):
    """获取探测历史日志。"""
    reports_dir = Path(config_mgr.project_root) / "reports"
    history_file = reports_dir / "probe_history.json"
    if not history_file.exists():
        return []
    try:
        mtime = history_file.stat().st_mtime
        if _HISTORY_CACHE["mtime"] == mtime:
            # 缓存命中，直接从内存返回，免除重复 I/O 及 JSON 反序列化
            return _HISTORY_CACHE["data"]
            
        data = json.loads(history_file.read_text(encoding="utf-8"))
        _HISTORY_CACHE["mtime"] = mtime
        _HISTORY_CACHE["data"] = data
        return data
    except Exception:
        return []

@router.delete("/history", status_code=status.HTTP_204_NO_CONTENT)
async def clear_test_history(config_mgr = Depends(get_config_manager)):
    """清空探测历史日志。"""
    reports_dir = Path(config_mgr.project_root) / "reports"
    history_file = reports_dir / "probe_history.json"
    if history_file.exists():
        try:
            history_file.unlink()
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"清空日志失败: {e}"
            )
    return
