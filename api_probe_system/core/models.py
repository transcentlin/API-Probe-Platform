# 修改历史 (Revision History)
# ==================================
# 版本: v1.7
# 日期: 2026-06-16
# 修改说明: 在 ProbeContext 中新增 total_duration_s 字段用于记录并展示大模型平台 6 阶段完整探测的全部总耗时。
# ----------------------------------
# 版本: v1.6
# 日期: 2026-06-15
# 修改说明: 在 PlatformConfig 中新增 discovery_handler 字段，支持通过配置明确指定各个平台采用哪种模型发现处理器（如 openai, cloudflare, ollama 等），实现非标端点动态获取逻辑的解耦。
# ==================================
# 版本: v1.5
# 日期: 2026-06-15
# 修改说明: 在 EndpointDiscoveryResult 中新增 error_message 字段，记录获取平台模型列表时的底层错误，避免静默失败造成排查困难。
# ==================================
# 版本: v1.4
# 日期: 2026-06-15
# 修改说明: 使 UserConfig.platforms 支持可选，默认列表为空，支持在 platforms 移出 YAML 文件后仍通过 Schema 验证。
# ==================================
# 版本: v1.3
# 日期: 2026-06-15
# 修改说明: 更新 ModelLimits 类型标注，使 max_tokens 和 max_context_length 支持 Union[int, str]，用于记录无法探测的具体成因。
# ==================================
# 版本: v1.2
# 日期: 2026-06-15
# 修改说明: 在 ModelLimits 类中新增 rate_limit_source 字段，用于记录速率限制的检测来源。
# ==================================
# 版本: v1.1
# 日期: 2026-06-15
# 修改说明: 在 CapabilityResult 中新增 retry_after_s 字段用于被动捕获限流重试秒数
# ==================================

"""核心数据模型（Pydantic + dataclass）。

定义贯穿探测流程的数据结构：
    - Platform / PlatformConfig：平台配置（对应 user_config.yaml）
    - ProbeContext：6 阶段共享上下文（详细设计 §2.3）
    - 各阶段产出：ConnectivityResult / FormatDetectionResult / EndpointDiscoveryResult 等
    - CapabilityResult：单项能力探测结果（详细设计 §2.6）
    - StageFailure：阶段失败记录
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, HttpUrl

# ──────────────────────────────────────────────────────────────────────────
# 平台配置（对应 user_config.yaml platforms[] 项）
# ──────────────────────────────────────────────────────────────────────────


class Hints(BaseModel):
    """用户提供的可选提示（对应 Schema hints 字段）。"""

    format: Optional[str] = None
    models: Optional[list[str]] = None
    endpoints: Optional[dict[str, str]] = None


class PlatformConfig(BaseModel):
    """平台配置（对应 Schema platforms[] 项，详细设计 §9.1）。"""

    model_config = ConfigDict(str_strip_whitespace=True)

    name: str = Field(min_length=1, description="平台唯一标识")
    base_url: str = Field(min_length=1, description="API 基础 URL（支持 ${ENV} 引用）")
    api_key: str = Field(min_length=1, description="API 密钥（支持 ${ENV} 引用）")
    website: Optional[HttpUrl] = Field(None, description="平台官网")
    notes: Optional[str] = Field(None, description="备注")
    hints: Optional[Hints] = Field(None, description="可选提示")
    discovery_handler: Optional[str] = Field("openai", description="模型发现处理器标识")


class TimeoutsConfig(BaseModel):
    """探针响应分级阈值的 YAML 配置（对应 defaults.timeouts 节）。

    所有字段可选；未提供则使用 ProbeTimeouts 的代码默认值。
    """

    fast_threshold_ms: Optional[int] = Field(
        None, gt=0, description="健康响应上限：首字节 < 此值为 HEALTHY（默认 30000）"
    )
    slow_threshold_ms: Optional[int] = Field(
        None, gt=0, description="半死不活上限：< 此值为 SLUGGISH，> 此值为 DEAD（默认 60000）"
    )
    connect_timeout_s: Optional[float] = Field(
        None, gt=0, description="TCP 连接超时（默认 10.0 秒）"
    )


class DeepProbeConfig(BaseModel):
    """深度探测参数（对应 defaults.deep_probe 节）。"""

    top_n: int = Field(default=3, ge=1, description="Stage4/5 覆盖排名前 N 的可用模型（默认 3）")


class DefaultsConfig(BaseModel):
    """全局默认配置（对应 defaults 节）。"""

    model_config = ConfigDict(extra="allow")

    timeouts: Optional[TimeoutsConfig] = None
    deep_probe: Optional[DeepProbeConfig] = None


class UserConfig(BaseModel):
    """user_config.yaml 根结构（对应 Schema 根对象）。"""

    platforms: list[PlatformConfig] = Field(default_factory=list)
    defaults: Optional[DefaultsConfig] = None
    overrides: Optional[dict[str, Any]] = None


# ──────────────────────────────────────────────────────────────────────────
# 阶段产出数据结构
# ──────────────────────────────────────────────────────────────────────────


@dataclass
class ConnectivityResult:
    """Stage0 预检查产出（详细设计 §2.4 Stage0）。"""

    reachable: bool
    status_code: Optional[int] = None
    latency_ms: Optional[float] = None
    website_title: Optional[str] = None  # 从 website 抓取的标题
    error: Optional[str] = None


@dataclass
class FormatDetectionResult:
    """Stage1 格式识别产出（详细设计 §2.4 Stage1）。"""

    detected_format: str  # FORMAT_OPENAI / FORMAT_ANTHROPIC / FORMAT_GEMINI
    confidence: float  # 0~1，最高分适配器的打分
    scores: dict[str, float] = field(default_factory=dict)  # 各适配器打分详情


@dataclass
class EndpointDiscoveryResult:
    """Stage2 端点发现产出（详细设计 §2.4 Stage2）。

    M2++ 增强：保留平台 /models 接口原生返回的 status 字段，
    供 Stage2.5 直接判定（如 BlazeAI 的 dead/degraded/healthy），
    避免对已知不可用模型再发探测请求。
    """

    endpoints: dict[str, str]  # 如 {"chat": "/v1/chat/completions", "models": "/v1/models"}
    models: list[str]  # 发现的模型 ID 列表
    discovery_method: str  # "api" / "hint" / "fallback"
    # 平台原生状态：{model_id: raw_status_str}，无该字段或值为空时不写入
    model_status: dict[str, str] = field(default_factory=dict)
    error_message: Optional[str] = None


@dataclass
class ModelAvailabilityCheckResult:
    """Stage2.5 模型可用性预检产出（M2 新增）。

    设计理念：快速筛选不可用模型，避免浪费 Stage3 配额。
    实测效果（Nvidia 案例）：118 个模型 → 10 个可用，节省 92% 请求量。
    """

    available_models: list[str]  # 可用模型列表
    unavailable_models: dict[str, dict]  # {model_id: {reason, status_code, error}}
    check_duration_ms: float  # 预检总耗时
    # 降级可用旁路标记：平台标 degraded 但实测通过的模型 {model_id: raw_status}
    degraded_models: dict[str, str] = field(default_factory=dict)

    def availability_rate(self) -> float:
        """计算可用率 = 可用模型数 / 总模型数。"""
        total = len(self.available_models) + len(self.unavailable_models)
        if total == 0:
            return 0.0
        return len(self.available_models) / total


@dataclass
class CapabilityResult:
    """单项能力探测结果（详细设计 §2.6）。

    M2 增强：新增模型可用性字段，支持不可用原因识别。
    """

    # M1 原有字段
    supported: Optional[bool]  # True/False/None(未测)
    reliability: str  # 'high'/'medium'/'low'/'unknown'
    detail: Optional[str] = None  # 如 vision 的 'url:✓ base64:✗'
    tested_at: datetime = field(default_factory=datetime.now)

    # M2 新增字段（仅 BasicChatProbe 填充，其他探针保持 None）
    availability: Optional[str] = None  # ModelAvailability 枚举值
    unavailable_reason: Optional[str] = None  # UnavailableReason 枚举值
    error_code: Optional[int] = None  # HTTP 状态码
    error_message: Optional[str] = None  # 错误详情
    latency_ms: Optional[float] = None  # 总响应延迟（毫秒）

    # M2+ 增强字段（响应分级 + 错误细分 + 流式 fallback）
    response_health: Optional[str] = None       # ResponseHealth 枚举值
    error_category: Optional[str] = None        # ErrorCategory 枚举值（比 unavailable_reason 更细）
    first_byte_latency_ms: Optional[float] = None  # 首字节延迟（流式时为首块到达时间）
    response_mode: Optional[str] = None         # "non_streaming" / "streaming_fallback" / "streaming"
    transport_used: Optional[str] = None        # 实际使用的传输方式 "non_streaming" / "streaming" / "circuit_breaker"
    retry_after_s: Optional[int] = None         # 被动捕获的 429 报错 Retry-After 间隔（秒）


@dataclass
class ProbeTimeouts:
    """探针超时与响应分级阈值配置。

    设计：注入到 BaseProbe，所有探针共用同一组阈值。
    YAML 未来可在 defaults.timeouts: 节配置，目前先用代码默认值。
    """

    fast_threshold_ms: int = 30_000   # 健康响应上限：< 此值为 HEALTHY
    slow_threshold_ms: int = 60_000   # 半死不活上限：< 此值为 SLUGGISH，> 此值为 DEAD
    connect_timeout_s: float = 10.0   # TCP 连接超时

    @property
    def total_timeout_s(self) -> float:
        """httpx 总超时（秒）= slow_threshold 的秒数，避免 30s 误杀半死不活模型。"""
        return self.slow_threshold_ms / 1000.0


@dataclass
class ModelLimits:
    """单模型边界探测结果。"""

    max_tokens: Optional[Union[int, str]] = None
    max_context_length: Optional[Union[int, str]] = None
    rate_limit_rpm: Optional[int] = None
    rate_limit_source: Optional[str] = None  # 速率限制获取来源（如 Header 提取/端点盲扫/429 反推/压测判定）


@dataclass
class LimitsResult:
    """Stage4 边界探测产出（per-model）。"""

    per_model: dict[str, ModelLimits] = field(default_factory=dict)


@dataclass
class ModelStability:
    """单模型稳定性分析结果。"""

    success_rate: float       # 0~1
    avg_latency_ms: float
    star_rating: int          # 1~5 星
    error_patterns: list[str] = field(default_factory=list)


@dataclass
class StabilityResult:
    """Stage5 稳定性分析产出（per-model + 平台汇总）。"""

    per_model: dict[str, ModelStability] = field(default_factory=dict)
    platform_success_rate: float = 0.0
    platform_star_rating: int = 1


@dataclass
class StageFailure:
    """阶段失败记录（详细设计 §2.3 ProbeContext.failures）。"""

    stage: int  # 0~5
    error_type: str  # 异常类名
    error_message: str
    timestamp: datetime = field(default_factory=datetime.now)


# ──────────────────────────────────────────────────────────────────────────
# ProbeContext：6 阶段共享上下文（详细设计 §2.3）
# ──────────────────────────────────────────────────────────────────────────


@dataclass
class ProbeContext:
    """探测上下文，贯穿 6 阶段，各阶段写入产出供后续阶段读取。"""

    # 输入
    platform: PlatformConfig
    mode: str  # ProbeMode 值
    session_id: Optional[int] = None  # 数据库会话 ID（引擎创建后回填）

    # Stage0 产出
    connectivity: Optional[ConnectivityResult] = None

    # Stage1 产出
    format_detection: Optional[FormatDetectionResult] = None

    # Stage2 产出
    endpoint_discovery: Optional[EndpointDiscoveryResult] = None

    # Stage2.5 产出（M2 新增）
    model_availability_check: Optional[ModelAvailabilityCheckResult] = None

    # Stage3 产出（M2 实现）
    capabilities: dict[str, CapabilityResult] = field(default_factory=dict)
    transport_modes: dict[str, str] = field(default_factory=dict)  # {model_id: TransportMode.value}

    # Stage4 产出（M2 实现）
    limits: Optional[LimitsResult] = None

    # Stage5 产出（M2 实现）
    stability: Optional[StabilityResult] = None

    # 总探测时间（秒）
    total_duration_s: Optional[float] = None

    # 失败记录
    failures: list[StageFailure] = field(default_factory=list)

    def add_failure(self, stage: int, error: Exception) -> None:
        """记录阶段失败（引擎调用）。"""
        self.failures.append(
            StageFailure(
                stage=stage,
                error_type=type(error).__name__,
                error_message=str(error),
            )
        )
