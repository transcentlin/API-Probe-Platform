# 修改历史 (Revision History)
# ==================================
# 版本: v1.0.0
# 日期: 2026-06-15
# 修改说明: 实现 FastAPI 依赖注入，用于统一提取并校验 PlatformManager 及 ConfigManager。
# ==================================

# -*- coding: utf-8 -*-
from fastapi import Request, HTTPException, status
from api_probe_system.core.platform_manager import PlatformManager
from api_probe_system.core.config import ConfigManager

def get_platform_manager(request: Request) -> PlatformManager:
    """获取 PlatformManager 单例，若未解密锁定则抛出 403。"""
    pm = getattr(request.app.state, "platform_manager", None)
    if pm is None or pm._master_password is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="系统尚未解锁，请先使用主密码解锁初始化平台注册表"
        )
    return pm

def get_config_manager(request: Request) -> ConfigManager:
    """获取 ConfigManager 单例。"""
    config_mgr = getattr(request.app.state, "config_manager", None)
    if config_mgr is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="ConfigManager 尚未初始化"
        )
    return config_mgr
