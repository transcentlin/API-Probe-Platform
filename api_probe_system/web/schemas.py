# 修改历史 (Revision History)
# ==================================
# 版本: v1.1.3
# 日期: 2026-06-16
# 修改说明: 为 PlatformUpdate 新增 name 可选配置项，以支持已创建平台名称的编辑和更新。
# ----------------------------------
# 版本: v1.1.2
# 日期: 2026-06-16
# 修改说明: 在 PlatformResponse 中新增 active_models_count 字段，以便向前端返回探测成功的可用模型总数。
# ----------------------------------
# 版本: v1.1.1
# 日期: 2026-06-15
# 修改说明: 新增 CompareRequest 校验 Schema，用于接收多平台对比 API 的请求参数体。
# ----------------------------------
# 版本: v1.1.0
# 日期: 2026-06-15
# 修改说明: 在 PlatformResponse 中新增 score 与 top_models 两个打分和推荐模型相关的字段。
# ----------------------------------
# 版本: v1.0.0
# 日期: 2026-06-15
# 修改说明: 实现 Web 接口所需的所有输入输出数据模型校验 (Pydantic)。
# ==================================

# -*- coding: utf-8 -*-
from typing import Optional, Any
from pydantic import BaseModel, Field

class HintsSchema(BaseModel):
    format: Optional[str] = None
    models: Optional[list[str]] = None
    endpoints: Optional[dict[str, str]] = None

class PlatformCreate(BaseModel):
    name: str = Field(..., min_length=1, description="平台名称")
    base_url: str = Field(..., min_length=1, description="API 基础 URL")
    api_key: str = Field(..., min_length=1, description="API 密钥")
    website: Optional[str] = Field("", description="平台官方主页")
    notes: Optional[str] = Field("", description="备注信息")
    hints: Optional[dict[str, Any]] = Field(default_factory=dict, description="嗅探引导 hints")
    discovery_handler: Optional[str] = Field("openai", description="模型发现处理器")

class PlatformUpdate(BaseModel):
    name: Optional[str] = None
    base_url: Optional[str] = None
    api_key: Optional[str] = None
    website: Optional[str] = None
    notes: Optional[str] = None
    hints: Optional[dict[str, Any]] = None
    discovery_handler: Optional[str] = None

class PlatformResponse(BaseModel):
    name: str
    base_url: str
    api_key: str  # 脱敏后的 api_key
    enabled: bool
    website: str
    notes: str
    hints: dict[str, Any]
    discovery_handler: str
    score: Optional[float] = None
    top_models: Optional[list[str]] = []
    active_models_count: int = 0

class PlatformToggle(BaseModel):
    enabled: bool

class TestStartRequest(BaseModel):
    platforms: list[str] = Field(..., min_length=1, description="需要运行测试的平台列表")
    mode: str = Field("standard", description="探测模式：quick/standard/deep")

class ReportResponse(BaseModel):
    filename: str = Field(..., description="文件名")
    size_bytes: int = Field(..., description="文件大小")
    platform_name: str = Field(..., description="所属平台名")
    created_at: str = Field(..., description="创建时间（格式化）")

class CompareRequest(BaseModel):
    platforms: Optional[list[str]] = Field(None, description="需要对比的平台名称列表，若为空则对比所有平台")
