# 修改历史 (Revision History)
# ==================================
# 版本: v1.1
# 日期: 2026-06-15
# 修改说明: 扩充 API 格式常量，支持包括 OpenAI Text、OpenAI Responses、Ollama、Cohere、DashScope 等在内的 8 种主流格式。
# ==================================

"""核心常量与异常定义。

集中定义全系统共享的枚举常量、阈值映射与异常类，避免散落各处导致魔法值。
对应：详细设计文档 §9.2 关键常量定义、§6.1 异常分类。
"""
from __future__ import annotations

from enum import Enum
from typing import Optional

# ──────────────────────────────────────────────────────────────────────────
# 探测模式与阶段映射（详细设计 §9.2）
# ──────────────────────────────────────────────────────────────────────────


class ProbeMode(str, Enum):
    """4 种探测模式（对应 FR-PROBE-09）。继承 str 便于 YAML/JSON 序列化。"""

    QUICK = "quick"
    STANDARD = "standard"
    DEEP = "deep"
    CUSTOM = "custom"


# 模式 → 执行的阶段编号列表；CUSTOM 由 options.stages 指定，故为 None
PROBE_MODE_STAGES: dict[str, list[int] | None] = {
    ProbeMode.QUICK.value: [0, 1, 2],
    ProbeMode.STANDARD.value: [0, 1, 2, 3],
    ProbeMode.DEEP.value: [0, 1, 2, 3, 4, 5],
    ProbeMode.CUSTOM.value: None,
}

# 已支持的 API 格式标识（对应 Schema format.detected 枚举）
FORMAT_OPENAI = "openai_chat_completions"
FORMAT_OPENAI_TEXT = "openai_text_completions"
FORMAT_OPENAI_RESP = "openai_responses"
FORMAT_OLLAMA = "ollama_native"
FORMAT_ANTHROPIC = "anthropic_messages"
FORMAT_GEMINI = "gemini_native"
FORMAT_COHERE = "cohere_native"
FORMAT_DASHSCOPE = "dashscope_native"

KNOWN_FORMATS: tuple[str, ...] = (
    FORMAT_OPENAI,
    FORMAT_OPENAI_TEXT,
    FORMAT_OPENAI_RESP,
    FORMAT_OLLAMA,
    FORMAT_ANTHROPIC,
    FORMAT_GEMINI,
    FORMAT_COHERE,
    FORMAT_DASHSCOPE,
)

# ──────────────────────────────────────────────────────────────────────────
# 评分阈值（详细设计 §9.2）
# ──────────────────────────────────────────────────────────────────────────

# 可靠性分级阈值：成功率 → 等级
RELIABILITY_THRESHOLDS: dict[str, float] = {
    "high": 0.95,
    "medium": 0.70,
    "low": 0.0,
}

# 稳定性星级映射：(成功率下限, 星级)，从高到低匹配
STABILITY_STAR_MAPPING: list[tuple[float, int]] = [
    (0.9, 5),
    (0.75, 4),
    (0.6, 3),
    (0.4, 2),
    (0.0, 1),
]


def reliability_grade(success_rate: float) -> str:
    """根据成功率映射可靠性等级。"""
    if success_rate >= RELIABILITY_THRESHOLDS["high"]:
        return "high"
    if success_rate >= RELIABILITY_THRESHOLDS["medium"]:
        return "medium"
    return "low"


def stability_stars(success_rate: float) -> int:
    """根据成功率映射稳定性星级（1~5）。"""
    for threshold, stars in STABILITY_STAR_MAPPING:
        if success_rate >= threshold:
            return stars
    return 1


# ──────────────────────────────────────────────────────────────────────────
# 阶段状态
# ──────────────────────────────────────────────────────────────────────────


class StageStatus(str, Enum):
    """单阶段执行结果状态（对应 stage_results.status）。"""

    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"


class SessionStatus(str, Enum):
    """探测会话状态（对应 probe_sessions.status / 任务状态机）。"""

    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    STOPPED = "stopped"


# ──────────────────────────────────────────────────────────────────────────
# 异常体系（详细设计 §6.1）
# ──────────────────────────────────────────────────────────────────────────


class ProbeSystemError(Exception):
    """系统异常基类，便于上层统一捕获。"""


class ConfigError(ProbeSystemError):
    """配置错误：环境变量未设置、URL 格式错误、必填字段缺失等（FR-CFG-05）。"""


class BudgetExceededError(ProbeSystemError):
    """请求预算超限（FR-TASK-06）。"""


class StageExecutionError(ProbeSystemError):
    """阶段执行内部错误，被引擎捕获记录后不向上中断（FR-PROBE-08）。"""


# ──────────────────────────────────────────────────────────────────────────
# M2 新增：模型可用性与探针类型（基于 M1 验证发现）
# ──────────────────────────────────────────────────────────────────────────


class ModelAvailability(str, Enum):
    """模型可用性状态（M2 核心枚举）。

    基于 M1 验证发现：模型列表 ≠ 可用模型。
    用于 BasicChatProbe 标记模型的可用性状态。
    """

    FULLY_AVAILABLE = "fully_available"          # 基础对话成功
    PARTIALLY_AVAILABLE = "partially_available"  # 基础对话成功但某些能力失败
    UNAVAILABLE = "unavailable"                  # 基础对话失败
    UNTESTED = "untested"                        # 尚未测试


class UnavailableReason(str, Enum):
    """模型不可用成因分类（M2 核心枚举）。

    基于 M1 验证的实测场景：
        - GitHub: 401 "Bad credentials" → AUTH_FAILED
        - Nvidia: 404 "Function not found for account" → PERMISSION_DENIED
        - FreetheAI: 403 "daily discord check-in required" → ACCESS_RESTRICTED

    注：PLATFORM_DEGRADED 已移除（语义矛盾：degraded 且实测通过的模型为可用，
    不应出现在不可用原因中）。降级可见性通过 ModelAvailabilityCheckResult.degraded_models 旁路标记承载。
    """

    AUTH_FAILED = "auth_failed"              # 401 认证失败
    PERMISSION_DENIED = "permission_denied"  # 403 权限不足 / 404 账户无权限
    MODEL_NOT_FOUND = "model_not_found"      # 404 模型不存在
    QUOTA_EXCEEDED = "quota_exceeded"        # 429 配额耗尽
    ACCESS_RESTRICTED = "access_restricted"  # 403 访问限制（签到门槛）
    PAYMENT_REQUIRED = "payment_required"    # 402 付费墙
    PLATFORM_DEAD = "platform_dead"          # 平台 /models 接口原生 status=dead
    NETWORK_ERROR = "network_error"          # TCP/DNS/超时/代理拦截 — 未收到 HTTP 响应
    UPSTREAM_ERROR = "upstream_error"        # HTTP 502/503/504 — 后端 provider 不可达
    SERVER_ERROR = "server_error"            # HTTP 500 及其它 5xx — 聚合站自身崩溃
    RESPONSE_INVALID = "response_invalid"    # HTTP 200/400 但 body 空/非法 JSON/SSE
    RESPONSE_INCOHERENT = "response_incoherent"  # HTTP 200 但语义崩溃（coherence 判定）
    UNKNOWN = "unknown"                      # 其他未知原因（兜底）


class ProbeType(str, Enum):
    """能力探针类型（M2 核心枚举）。

    对应 8 个能力探针（FR-CAP-01~08）。
    """

    BASIC_CHAT = "basic_chat"
    STREAMING = "streaming"
    TOOL_CALLING = "tool_calling"
    VISION = "vision"
    JSON_MODE = "json_mode"
    REASONING = "reasoning"
    WEB_SEARCH = "web_search"
    MULTI_TURN = "multi_turn"


class TransportMode(str, Enum):
    """模型传输模式（Stage3 Phase 1 Gateway 探测产出）。
    
    用于决定 Phase 2 扩展探针使用何种传输方式。
    """

    DUAL = "dual"                        # 非流式 + 流式均可用
    STREAMING_ONLY = "streaming_only"    # 仅流式可用（非流式返回空响应体）
    NON_STREAMING_ONLY = "non_streaming_only"  # 仅非流式可用（罕见）
    DEAD = "dead"                        # 双通道均不可用


# Gateway 探针名（Phase 1 优先执行，用于判定传输模式）
GATEWAY_PROBES: set[str] = {"basic_chat", "streaming"}


# ──────────────────────────────────────────────────────────────────────────
# M2+ 增强：响应分级 + 错误细分（探针准确度增强）
# ──────────────────────────────────────────────────────────────────────────

# 响应时长阈值默认值（毫秒）
DEFAULT_FAST_THRESHOLD_MS = 30_000   # 健康响应上限：30 秒
DEFAULT_SLOW_THRESHOLD_MS = 60_000   # 半死不活上限：60 秒
DEFAULT_CONNECT_TIMEOUT_S = 10.0     # TCP 连接超时


class ResponseHealth(str, Enum):
    """响应健康度三级分级。

    判定依据：首字节延迟（流式 = 首块到达时间，非流式 = 总耗时）。
    阈值由 ProbeTimeouts 决定，默认 30s / 60s。
    """

    HEALTHY = "healthy"      # 首字节 < fast_threshold（默认 30s）
    SLUGGISH = "sluggish"    # 首字节在 [fast, slow]（默认 30~60s）
    DEAD = "dead"            # 首字节 > slow_threshold 或抛错


class ErrorCategory(str, Enum):
    """错误细分类（TCP / HTTP / 应用三层）。

    比 UnavailableReason 更细粒度，用于精确归因。
    现有 UnavailableReason 仍保留作为不可用模型的聚合分类。
    """

    # 网络层（TCP / 传输）
    CONNECT_FAILED = "connect_failed"          # DNS 失败 / 端口拒绝（httpx.ConnectError）
    READ_TIMEOUT = "read_timeout"              # 已建连接超过 slow_threshold（TimeoutException）
    OTHER_SIDE_CLOSED = "other_side_closed"    # 上游主动断连（RemoteProtocolError / ReadError）
    PROXY_BLOCKED = "proxy_blocked"            # 代理软件关键词拦截

    # HTTP 层
    HTTP_AUTH = "http_auth"                    # 401
    HTTP_FORBIDDEN = "http_forbidden"          # 403
    HTTP_NOT_FOUND = "http_not_found"          # 404
    HTTP_RATE_LIMITED = "http_rate_limited"    # 429
    HTTP_PAYMENT_REQUIRED = "http_payment_required"  # 402
    HTTP_UPSTREAM_ERROR = "http_upstream_error"      # 502/503/504
    HTTP_SERVER_ERROR = "http_server_error"          # 500 及其他 5xx

    # 应用层
    EMPTY_RESPONSE = "empty_response"            # HTTP 200 但响应体空
    MALFORMED_RESPONSE = "malformed_response"    # HTTP 200 但 JSON/SSE 不合规
    INCOHERENT_RESPONSE = "incoherent_response"  # 语义崩溃（coherence 模块判定）

    UNKNOWN = "unknown"


def classify_response_health(
    first_byte_latency_ms: Optional[float],
    fast_threshold_ms: int = DEFAULT_FAST_THRESHOLD_MS,
    slow_threshold_ms: int = DEFAULT_SLOW_THRESHOLD_MS,
) -> str:
    """将首字节延迟映射到 ResponseHealth 枚举值。

    Args:
        first_byte_latency_ms: 首字节延迟（毫秒）。None 视为 DEAD。
        fast_threshold_ms: 健康响应上限
        slow_threshold_ms: 半死不活上限

    Returns:
        ResponseHealth 枚举的 value。
    """
    if first_byte_latency_ms is None:
        return ResponseHealth.DEAD.value
    if first_byte_latency_ms < fast_threshold_ms:
        return ResponseHealth.HEALTHY.value
    if first_byte_latency_ms < slow_threshold_ms:
        return ResponseHealth.SLUGGISH.value
    return ResponseHealth.DEAD.value
