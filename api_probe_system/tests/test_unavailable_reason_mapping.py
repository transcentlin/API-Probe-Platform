"""单元测试：UnavailableReason 映射（方案 D 验证）。

覆盖：
1. ErrorCategory → UnavailableReason 映射表（全 13 项）
2. HTTP 状态码扩展映射（400 / 5xx / 罕见 4xx）
3. _build_network_error_result 不再硬塞 UNKNOWN
"""
import pytest

from api_probe_system.core.constants import ErrorCategory, UnavailableReason
from api_probe_system.core.probes.base import BaseProbe, _reason_from_category


# ──────────────────────────────────────────────────────────────────
# 1. ErrorCategory → UnavailableReason 映射表
# ──────────────────────────────────────────────────────────────────

CATEGORY_REASON_CASES = [
    # 网络层 4 项 → NETWORK_ERROR
    (ErrorCategory.CONNECT_FAILED.value,       UnavailableReason.NETWORK_ERROR.value),
    (ErrorCategory.READ_TIMEOUT.value,         UnavailableReason.NETWORK_ERROR.value),
    (ErrorCategory.OTHER_SIDE_CLOSED.value,    UnavailableReason.NETWORK_ERROR.value),
    (ErrorCategory.PROXY_BLOCKED.value,        UnavailableReason.NETWORK_ERROR.value),
    # HTTP 层 5 项 → 原分类
    (ErrorCategory.HTTP_AUTH.value,            UnavailableReason.AUTH_FAILED.value),
    (ErrorCategory.HTTP_FORBIDDEN.value,       UnavailableReason.PERMISSION_DENIED.value),
    (ErrorCategory.HTTP_NOT_FOUND.value,       UnavailableReason.MODEL_NOT_FOUND.value),
    (ErrorCategory.HTTP_RATE_LIMITED.value,    UnavailableReason.QUOTA_EXCEEDED.value),
    (ErrorCategory.HTTP_PAYMENT_REQUIRED.value, UnavailableReason.PAYMENT_REQUIRED.value),
    # 应用层 3 项 → 新枚举
    (ErrorCategory.EMPTY_RESPONSE.value,       UnavailableReason.RESPONSE_INVALID.value),
    (ErrorCategory.MALFORMED_RESPONSE.value,   UnavailableReason.RESPONSE_INVALID.value),
    (ErrorCategory.INCOHERENT_RESPONSE.value,  UnavailableReason.RESPONSE_INCOHERENT.value),
    # 兜底
    (ErrorCategory.UNKNOWN.value,              UnavailableReason.UNKNOWN.value),
]


@pytest.mark.parametrize("category,expected", CATEGORY_REASON_CASES)
def test_reason_from_category_mapping(category, expected):
    """_reason_from_category 覆盖全部 13 个 ErrorCategory。"""
    assert _reason_from_category(category) == expected


def test_reason_from_category_fallback_unknown():
    """未知 category 字符串兜底 UNKNOWN。"""
    assert _reason_from_category("something_nonexistent") == UnavailableReason.UNKNOWN.value


# ──────────────────────────────────────────────────────────────────
# 2. HTTP 状态码扩展映射
# ──────────────────────────────────────────────────────────────────

STATUS_REASON_CASES = [
    # 标准认证/权限/模型类 — 保持原分类
    (401, UnavailableReason.AUTH_FAILED),
    (402, UnavailableReason.PAYMENT_REQUIRED),
    (429, UnavailableReason.QUOTA_EXCEEDED),
    # 新增扩展
    (400, UnavailableReason.RESPONSE_INVALID),
    (500, UnavailableReason.SERVER_ERROR),
    (502, UnavailableReason.UPSTREAM_ERROR),
    (503, UnavailableReason.UPSTREAM_ERROR),
    (504, UnavailableReason.UPSTREAM_ERROR),
    (599, UnavailableReason.SERVER_ERROR),
    # 罕见 4xx 仍兜底 UNKNOWN
    (408, UnavailableReason.UNKNOWN),
    (418, UnavailableReason.UNKNOWN),
]


class _FakeResponse:
    """轻量 fake，仅模拟 status_code 和可空 JSON body。"""

    def __init__(self, status_code: int, body: dict | None = None):
        self.status_code = status_code
        self._body = body or {}

    def json(self) -> dict:
        return self._body

    @property
    def text(self):
        return str(self._body)


@pytest.mark.parametrize("status_code,expected", STATUS_REASON_CASES)
def test_infer_unavailable_reason_by_status(status_code, expected):
    """_infer_unavailable_reason 覆盖新扩展状态码。"""
    probe = BaseProbe()
    response = _FakeResponse(status_code)
    result = probe._infer_unavailable_reason(response)
    assert result == expected


STATUS_VALUE_CASES = [
    (400, UnavailableReason.RESPONSE_INVALID.value),
    (500, UnavailableReason.SERVER_ERROR.value),
    (502, UnavailableReason.UPSTREAM_ERROR.value),
    (503, UnavailableReason.UPSTREAM_ERROR.value),
    (504, UnavailableReason.UPSTREAM_ERROR.value),
    (599, UnavailableReason.SERVER_ERROR.value),
    (418, UnavailableReason.UNKNOWN.value),
]


@pytest.mark.parametrize("status_code,expected_value", STATUS_VALUE_CASES)
def test_http_status_to_unavailable_reason_extended(status_code, expected_value):
    """_http_status_to_unavailable_reason（流式无 body 版本）扩展状态码。"""
    probe = BaseProbe()
    result = probe._http_status_to_unavailable_reason(status_code)
    assert result == expected_value


# ──────────────────────────────────────────────────────────────────
# 3. _build_network_error_result 不再硬塞 UNKNOWN
# ──────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("category,expected_reason", [
    (ErrorCategory.CONNECT_FAILED.value,    UnavailableReason.NETWORK_ERROR.value),
    (ErrorCategory.READ_TIMEOUT.value,      UnavailableReason.NETWORK_ERROR.value),
    (ErrorCategory.OTHER_SIDE_CLOSED.value, UnavailableReason.NETWORK_ERROR.value),
    (ErrorCategory.PROXY_BLOCKED.value,     UnavailableReason.NETWORK_ERROR.value),
    (ErrorCategory.UNKNOWN.value,           UnavailableReason.UNKNOWN.value),
])
def test_build_network_error_result_uses_mapped_reason(category, expected_reason):
    """网络层错误结果的 unavailable_reason 应反映映射表，不再硬编码 UNKNOWN。"""
    probe = BaseProbe()
    result = probe._build_network_error_result(category, "test error msg")
    assert result.unavailable_reason == expected_reason
    assert result.error_category == category  # 细分类保留
    assert result.supported is False
