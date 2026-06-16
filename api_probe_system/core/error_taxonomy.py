"""错误分类单一信息源（Error Taxonomy）。

所有「探测信号 → ErrorCategory + UnavailableReason」的对应关系集中在此模块。
外部调用者只需调用 classify(signal) → Diagnosis，不再散落在 4 个文件里手写 if/elif。

设计原则：
    - ErrorSignal：归一化 4 种输入形态的纯数据容器
    - Diagnosis：分类结果，仅含枚举值，不含文案
    - ClassificationRule：单条规则的纯数据描述
    - CLASSIFICATION_RULES：有序规则表（第一条命中即返回）
    - classify()：按列表顺序遍历规则，返回 Diagnosis

优先级分层（从高到低）：
    app_signal → 异常类型 → native_status → 平台特异+关键词 → 平台特异+纯状态码
    → 通用+关键词 → 通用+纯状态码 → 兜底 UNKNOWN

展示文案（REASON_META / CATEGORY_META）也集中在此，reporter.py 从此导入。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Type

import httpx

from .constants import ErrorCategory, UnavailableReason


# ──────────────────────────────────────────────────────────────────────────
# 核心三件套
# ──────────────────────────────────────────────────────────────────────────


@dataclass
class ErrorSignal:
    """归一化的错误信号容器。

    调用方将各种输入形态（httpx 异常、HTTP 响应、app 层信号、平台 native 状态）
    转换成此结构体，再交给 classify() 分类。
    """
    # HTTP 层
    status_code: Optional[int] = None
    body_text: Optional[str] = None          # 已小写的响应体文本

    # 异常层
    exception: Optional[Exception] = None
    exc_message: Optional[str] = None        # 已小写的异常文本
    exc_type_name: Optional[str] = None      # 异常类名（Stage5 细粒度标签透传）

    # 应用信号
    app_signal: Optional[str] = None         # "empty" / "malformed" / "incoherent"

    # 平台 /models 接口原生状态
    native_status: Optional[str] = None      # "dead" / "degraded" / ...

    # 平台标识（已转小写）
    platform_name: Optional[str] = None


@dataclass
class Diagnosis:
    """分类结果：ErrorCategory + UnavailableReason 同时产出，消除两层不对称。"""
    error_category: str    # ErrorCategory.value
    unavailable_reason: str  # UnavailableReason.value


@dataclass
class ClassificationRule:
    """单条分类规则（纯数据）。

    字段含义：
        status_codes      精确匹配状态码列表（OR）
        status_range      (min_inclusive, max_exclusive) 范围匹配（与 status_codes 互斥，OR 关系）
        body_keywords     body_text 包含其中任一关键词（OR）
        exception_types   isinstance 类型检查（OR）；顺序敏感，父类放后
        exc_keywords      exc_message 必须包含所有关键词（AND）
        app_signal        精确匹配 app_signal 字符串
        native_status     精确匹配 native_status 字符串
        platforms         限定平台名称（OR）；空列表 = 通用规则
        category          命中时产出的 ErrorCategory.value
        reason            命中时产出的 UnavailableReason.value
    """
    category: str
    reason: str

    status_codes: list[int] = field(default_factory=list)
    status_range: Optional[tuple[int, int]] = None       # [min, max)
    body_keywords: list[str] = field(default_factory=list)
    exception_types: list[type] = field(default_factory=list)
    exc_keywords: list[str] = field(default_factory=list)  # AND 语义
    app_signal: Optional[str] = None
    native_status: Optional[str] = None
    platforms: list[str] = field(default_factory=list)   # 空=通用


def _rule(
    category: str,
    reason: str,
    *,
    status_codes: list[int] | None = None,
    status_range: tuple[int, int] | None = None,
    body_keywords: list[str] | None = None,
    exception_types: list[type] | None = None,
    exc_keywords: list[str] | None = None,
    app_signal: str | None = None,
    native_status: str | None = None,
    platforms: list[str] | None = None,
) -> ClassificationRule:
    """规则工厂函数，减少重复的 field(default_factory=list)。"""
    return ClassificationRule(
        category=category,
        reason=reason,
        status_codes=status_codes or [],
        status_range=status_range,
        body_keywords=body_keywords or [],
        exception_types=exception_types or [],
        exc_keywords=exc_keywords or [],
        app_signal=app_signal,
        native_status=native_status,
        platforms=platforms or [],
    )


# ──────────────────────────────────────────────────────────────────────────
# 有序规则表（第一条命中即返回）
# ──────────────────────────────────────────────────────────────────────────

CLASSIFICATION_RULES: list[ClassificationRule] = [

    # ── 1. 应用层信号（最先匹配，避免被 HTTP 状态码规则抢走）
    _rule(
        ErrorCategory.EMPTY_RESPONSE.value,
        UnavailableReason.RESPONSE_INVALID.value,
        app_signal="empty",
    ),
    _rule(
        ErrorCategory.MALFORMED_RESPONSE.value,
        UnavailableReason.RESPONSE_INVALID.value,
        app_signal="malformed",
    ),
    _rule(
        ErrorCategory.INCOHERENT_RESPONSE.value,
        UnavailableReason.RESPONSE_INCOHERENT.value,
        app_signal="incoherent",
    ),

    # ── 2. 平台 /models 原生状态
    _rule(
        ErrorCategory.UNKNOWN.value,
        UnavailableReason.PLATFORM_DEAD.value,
        native_status="dead",
    ),
    _rule(
        ErrorCategory.UNKNOWN.value,
        UnavailableReason.PLATFORM_DEAD.value,
        native_status="offline",
    ),

    # ── 3. 代理拦截（异常 AND 关键词，必须排在其他异常类型之前）
    _rule(
        ErrorCategory.PROXY_BLOCKED.value,
        UnavailableReason.NETWORK_ERROR.value,
        exception_types=[httpx.ConnectError, httpx.HTTPError],
        exc_keywords=["access denied", "network settings"],  # AND 语义
    ),

    # ── 4. 连接层异常（ConnectTimeout 必须在 TimeoutException 前，因为是子类）
    _rule(
        ErrorCategory.CONNECT_FAILED.value,
        UnavailableReason.NETWORK_ERROR.value,
        exception_types=[httpx.ConnectTimeout],
    ),
    _rule(
        ErrorCategory.CONNECT_FAILED.value,
        UnavailableReason.NETWORK_ERROR.value,
        exception_types=[httpx.ConnectError],
    ),
    _rule(
        ErrorCategory.READ_TIMEOUT.value,
        UnavailableReason.NETWORK_ERROR.value,
        exception_types=[httpx.ReadTimeout],
    ),
    _rule(
        ErrorCategory.READ_TIMEOUT.value,
        UnavailableReason.NETWORK_ERROR.value,
        exception_types=[httpx.TimeoutException],
    ),
    _rule(
        ErrorCategory.OTHER_SIDE_CLOSED.value,
        UnavailableReason.NETWORK_ERROR.value,
        exception_types=[httpx.RemoteProtocolError, httpx.ReadError],
    ),

    # ── 5. 平台特异规则（带 platforms 限定，优先于通用规则）

    # FreetheAI：403 + 签到关键词
    _rule(
        ErrorCategory.HTTP_FORBIDDEN.value,
        UnavailableReason.ACCESS_RESTRICTED.value,
        platforms=["freetheai"],
        status_codes=[403],
        body_keywords=["check-in", "checkin", "discord"],
    ),

    # Nvidia：404 + 精确账户无权限短语
    _rule(
        ErrorCategory.HTTP_NOT_FOUND.value,
        UnavailableReason.PERMISSION_DENIED.value,
        platforms=["nvidia"],
        status_codes=[404],
        body_keywords=["not found for account"],
    ),

    # ── 6. 通用 HTTP 规则（带关键词，优先于纯状态码兜底）

    # 401
    _rule(
        ErrorCategory.HTTP_AUTH.value,
        UnavailableReason.AUTH_FAILED.value,
        status_codes=[401],
    ),

    # 403 签到（非 freetheai 平台也可能有）
    _rule(
        ErrorCategory.HTTP_FORBIDDEN.value,
        UnavailableReason.ACCESS_RESTRICTED.value,
        status_codes=[403],
        body_keywords=["check-in", "checkin", "discord"],
    ),
    # 403 付费墙
    _rule(
        ErrorCategory.HTTP_FORBIDDEN.value,
        UnavailableReason.PAYMENT_REQUIRED.value,
        status_codes=[403],
        body_keywords=["payment", "billing", "subscription"],
    ),
    # 403 权限相关关键词
    _rule(
        ErrorCategory.HTTP_FORBIDDEN.value,
        UnavailableReason.PERMISSION_DENIED.value,
        status_codes=[403],
        body_keywords=["permission", "unauthorized"],
    ),
    # 403 兜底
    _rule(
        ErrorCategory.HTTP_FORBIDDEN.value,
        UnavailableReason.PERMISSION_DENIED.value,
        status_codes=[403],
    ),

    # 404 精确短语（Nvidia 通用化）
    _rule(
        ErrorCategory.HTTP_NOT_FOUND.value,
        UnavailableReason.PERMISSION_DENIED.value,
        status_codes=[404],
        body_keywords=["not found for account"],
    ),
    # 404 兜底
    _rule(
        ErrorCategory.HTTP_NOT_FOUND.value,
        UnavailableReason.MODEL_NOT_FOUND.value,
        status_codes=[404],
    ),

    # 429
    _rule(
        ErrorCategory.HTTP_RATE_LIMITED.value,
        UnavailableReason.QUOTA_EXCEEDED.value,
        status_codes=[429],
    ),

    # 402
    _rule(
        ErrorCategory.HTTP_PAYMENT_REQUIRED.value,
        UnavailableReason.PAYMENT_REQUIRED.value,
        status_codes=[402],
    ),

    # 400（参数不被接受，如视觉模型拒收 image_url）
    _rule(
        ErrorCategory.MALFORMED_RESPONSE.value,
        UnavailableReason.RESPONSE_INVALID.value,
        status_codes=[400],
    ),

    # 5xx：上游故障（502/503/504）
    _rule(
        ErrorCategory.HTTP_UPSTREAM_ERROR.value,
        UnavailableReason.UPSTREAM_ERROR.value,
        status_codes=[502, 503, 504],
    ),

    # 5xx：服务端错误（500 + 其他 5xx）
    _rule(
        ErrorCategory.HTTP_SERVER_ERROR.value,
        UnavailableReason.SERVER_ERROR.value,
        status_range=(500, 600),
    ),

    # ── 7. 兜底
    _rule(
        ErrorCategory.UNKNOWN.value,
        UnavailableReason.UNKNOWN.value,
    ),
]


# ──────────────────────────────────────────────────────────────────────────
# 分类引擎
# ──────────────────────────────────────────────────────────────────────────


def _rule_matches(rule: ClassificationRule, sig: ErrorSignal) -> bool:
    """判断单条规则是否匹配 signal。所有非空条件 AND，每个列表字段内部 OR。"""

    # 平台限定
    if rule.platforms:
        if not sig.platform_name or sig.platform_name not in rule.platforms:
            return False

    # app_signal 精确匹配
    if rule.app_signal is not None:
        if sig.app_signal != rule.app_signal:
            return False

    # native_status 精确匹配
    if rule.native_status is not None:
        if not sig.native_status or sig.native_status.lower() != rule.native_status:
            return False

    # 异常类型（OR，isinstance）
    if rule.exception_types:
        if sig.exception is None:
            return False
        if not any(isinstance(sig.exception, t) for t in rule.exception_types):
            return False
        # exc_keywords AND 语义（仅在 exception_types 命中后检查）
        if rule.exc_keywords:
            msg = sig.exc_message or ""
            if not all(kw in msg for kw in rule.exc_keywords):
                return False
        return True  # 异常规则不再检查 status_code

    # 状态码匹配（精确列表 OR 范围）
    if rule.status_codes or rule.status_range:
        if sig.status_code is None:
            return False
        if rule.status_codes and sig.status_code not in rule.status_codes:
            if not (
                rule.status_range
                and rule.status_range[0] <= sig.status_code < rule.status_range[1]
            ):
                return False
        if rule.status_range and not rule.status_codes:
            if not (rule.status_range[0] <= sig.status_code < rule.status_range[1]):
                return False

        # body_keywords OR 语义
        if rule.body_keywords:
            body = sig.body_text or ""
            if not any(kw in body for kw in rule.body_keywords):
                return False

        return True

    # 纯兜底规则（无任何匹配条件）
    return True


def classify(signal: ErrorSignal) -> Diagnosis:
    """将 ErrorSignal 分类为 Diagnosis（category + reason 同时产出）。

    按 CLASSIFICATION_RULES 列表顺序匹配，第一条命中即返回。
    """
    for rule in CLASSIFICATION_RULES:
        if _rule_matches(rule, signal):
            return Diagnosis(
                error_category=rule.category,
                unavailable_reason=rule.reason,
            )
    # 理论上不可达（最后一条是无条件兜底）
    return Diagnosis(
        error_category=ErrorCategory.UNKNOWN.value,
        unavailable_reason=UnavailableReason.UNKNOWN.value,
    )


def signal_from_exception(
    exc: Exception,
    *,
    platform_name: Optional[str] = None,
    slow_threshold_ms: int = 60000,
) -> ErrorSignal:
    """将 httpx 异常转换为 ErrorSignal 的便捷工厂函数。"""
    exc_msg = str(exc).lower()
    return ErrorSignal(
        exception=exc,
        exc_message=exc_msg,
        exc_type_name=type(exc).__name__,
        platform_name=platform_name.lower() if platform_name else None,
    )


def signal_from_response(
    response: httpx.Response,
    *,
    platform_name: Optional[str] = None,
) -> ErrorSignal:
    """将 httpx.Response 转换为 ErrorSignal 的便捷工厂函数。

    按「先 JSON 再 text」降级逻辑提取 body_text。
    """
    try:
        body = response.json()
        body_text = str(body).lower()
    except Exception:
        body_text = response.text.lower()

    return ErrorSignal(
        status_code=response.status_code,
        body_text=body_text,
        platform_name=platform_name.lower() if platform_name else None,
    )


# ──────────────────────────────────────────────────────────────────────────
# 展示文案单源
# ──────────────────────────────────────────────────────────────────────────

# 不可用成因 → (中文名, 严重程度, 成因说明, 修复建议)
REASON_META: dict[str, tuple[str, str, str, str]] = {
    UnavailableReason.AUTH_FAILED.value: (
        "认证失败", "高",
        "API Key 无效、已过期或套餐未包含该模型",
        "检查 API Key 是否正确，确认密钥类型与权限",
    ),
    UnavailableReason.PERMISSION_DENIED.value: (
        "权限不足", "中",
        "账户无权访问该模型",
        "申请模型授权或换用有权限的模型",
    ),
    UnavailableReason.MODEL_NOT_FOUND.value: (
        "模型不存在", "中",
        "模型 ID 有误或该模型已下线",
        "检查模型 ID 是否正确，或该模型已下线",
    ),
    UnavailableReason.QUOTA_EXCEEDED.value: (
        "配额耗尽", "中",
        "RPM 或余额限额已触顶",
        "等待配额重置或升级套餐",
    ),
    UnavailableReason.ACCESS_RESTRICTED.value: (
        "访问限制", "高",
        "平台要求完成特定解锁操作（如每日签到）",
        "完成平台要求的解锁动作（如 Discord 签到）",
    ),
    UnavailableReason.PAYMENT_REQUIRED.value: (
        "付费墙", "高",
        "该模型仅对付费套餐开放",
        "升级到付费套餐",
    ),
    UnavailableReason.PLATFORM_DEAD.value: (
        "平台标记死亡", "高",
        "平台 /models 接口原生标记该模型为 dead/offline",
        "弃用该模型",
    ),
    UnavailableReason.NETWORK_ERROR.value: (
        "网络异常", "中",
        "DNS 解析失败、连接超时或代理拦截",
        "检查本地网络/代理；持续失败则平台可能已关停",
    ),
    UnavailableReason.UPSTREAM_ERROR.value: (
        "上游故障", "高",
        "聚合站后端返回 502/503/504",
        "等待平台恢复或换聚合站",
    ),
    UnavailableReason.SERVER_ERROR.value: (
        "服务端错误", "高",
        "聚合站自身异常（HTTP 500）",
        "联系平台支持",
    ),
    UnavailableReason.RESPONSE_INVALID.value: (
        "响应异常", "中",
        "HTTP 200/400 但响应不可解析",
        "重试；持续出现则报告平台",
    ),
    UnavailableReason.RESPONSE_INCOHERENT.value: (
        "内容崩溃", "高",
        "模型语义乱码（权重/KV cache 异常）",
        "弃用该模型",
    ),
    UnavailableReason.UNKNOWN.value: (
        "未知", "低",
        "暂未归类，需查看错误详情",
        "查看错误详情，必要时联系平台支持",
    ),
}

# 错误细分类元数据 → (中文名, 表现, 根因, 处理建议)
CATEGORY_META: dict[str, tuple[str, str, str, str]] = {
    ErrorCategory.CONNECT_FAILED.value: (
        "连接失败", "DNS 失败 / 端口拒绝", "base_url 错或平台已关停", "检查 URL 与网络"
    ),
    ErrorCategory.READ_TIMEOUT.value: (
        "读取超时", "建连后无字节", "后端死锁 / 上游死", "重试或弃用"
    ),
    ErrorCategory.OTHER_SIDE_CLOSED.value: (
        "上游断连", "other_side_closed", "上游 provider 不可达", "弃用模型"
    ),
    ErrorCategory.PROXY_BLOCKED.value: (
        "代理拦截", "Access denied", "代理软件关键词拦截", "调整代理规则"
    ),
    ErrorCategory.HTTP_AUTH.value: (
        "认证失败", "HTTP 401", "API Key 错或过期", "更新密钥"
    ),
    ErrorCategory.HTTP_FORBIDDEN.value: (
        "权限不足", "HTTP 403", "账户无权访问", "升级套餐或换模型"
    ),
    ErrorCategory.HTTP_NOT_FOUND.value: (
        "模型不存在", "HTTP 404", "平台已下线", "改用其它模型"
    ),
    ErrorCategory.HTTP_RATE_LIMITED.value: (
        "配额耗尽", "HTTP 429", "RPM / 余额耗尽", "等待重置"
    ),
    ErrorCategory.HTTP_PAYMENT_REQUIRED.value: (
        "付费墙", "HTTP 402", "需付费套餐", "升级账户"
    ),
    ErrorCategory.HTTP_UPSTREAM_ERROR.value: (
        "上游故障", "HTTP 502/503/504", "聚合站后端 provider 不可达", "等待平台恢复或换聚合站"
    ),
    ErrorCategory.HTTP_SERVER_ERROR.value: (
        "服务端错误", "HTTP 500+", "聚合站自身崩溃", "联系平台支持"
    ),
    ErrorCategory.EMPTY_RESPONSE.value: (
        "空响应", "HTTP 200 + 空 body", "后端故障", "重试"
    ),
    ErrorCategory.MALFORMED_RESPONSE.value: (
        "格式异常", "HTTP 200 + 非法 JSON/SSE", "后端格式不规范", "检查平台兼容性"
    ),
    ErrorCategory.INCOHERENT_RESPONSE.value: (
        "内容乱码", "语义崩溃", "模型权重 / KV cache 损坏", "弃用模型"
    ),
    ErrorCategory.UNKNOWN.value: (
        "未知", "未归类异常", "需查看错误样本", "联系平台支持"
    ),
}
