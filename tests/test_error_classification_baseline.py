"""Step 0 基线快照测试：冻结现有 4 条分类路径的输出。

这批测试在重构前先跑通、钉死黄金输出。
重构后这批测试仍必须通过（新路径的输出 == 旧路径输出）。
预期 diff 清单（允许的有意差异）注释在各 case 旁边。
"""
from __future__ import annotations

import sys
import os
import unittest
from unittest.mock import MagicMock, patch, PropertyMock

# 把项目根目录加入 sys.path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import httpx

from api_probe_system.core.constants import ErrorCategory, UnavailableReason
from api_probe_system.core.probes.base import BaseProbe
from api_probe_system.core.models import ProbeTimeouts


def _make_probe() -> BaseProbe:
    """构造测试用 BaseProbe（使用默认超时）。"""
    timeouts = ProbeTimeouts(
        fast_threshold_ms=30000,
        slow_threshold_ms=60000,
        connect_timeout_s=10.0,
    )
    return BaseProbe(timeouts=timeouts)


def _make_response(status: int, body_text: str = "") -> httpx.Response:
    """构造 mock httpx.Response。"""
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status
    resp.text = body_text
    # json() 解析行为
    import json
    try:
        parsed = json.loads(body_text)
        resp.json.return_value = parsed
    except Exception:
        resp.json.side_effect = Exception("not json")
    return resp


# ──────────────────────────────────────────────────────────────────────────
# 路径 A：BaseProbe._classify_exception（异常 → ErrorCategory）
# ──────────────────────────────────────────────────────────────────────────


class TestClassifyException(unittest.TestCase):
    """BaseProbe._classify_exception 黄金输出快照。"""

    def setUp(self):
        self.probe = _make_probe()

    def test_proxy_blocked(self):
        """代理关键词 AND 匹配 → PROXY_BLOCKED。"""
        exc = httpx.ConnectError("Access denied by network settings")
        cat, msg = self.probe._classify_exception(exc)
        self.assertEqual(cat, ErrorCategory.PROXY_BLOCKED.value)

    def test_proxy_blocked_requires_both_keywords(self):
        """只有 'Access denied' 不够 → 不归 PROXY_BLOCKED。"""
        exc = httpx.ConnectError("Access denied")
        cat, msg = self.probe._classify_exception(exc)
        self.assertNotEqual(cat, ErrorCategory.PROXY_BLOCKED.value)

    def test_connect_timeout(self):
        """ConnectTimeout（TimeoutException 子类）→ CONNECT_FAILED。"""
        exc = httpx.ConnectTimeout("timeout")
        cat, msg = self.probe._classify_exception(exc)
        self.assertEqual(cat, ErrorCategory.CONNECT_FAILED.value)

    def test_connect_error(self):
        """ConnectError → CONNECT_FAILED。"""
        exc = httpx.ConnectError("connection refused")
        cat, msg = self.probe._classify_exception(exc)
        self.assertEqual(cat, ErrorCategory.CONNECT_FAILED.value)

    def test_read_timeout(self):
        """ReadTimeout → READ_TIMEOUT。"""
        exc = httpx.ReadTimeout("read timeout")
        cat, msg = self.probe._classify_exception(exc)
        self.assertEqual(cat, ErrorCategory.READ_TIMEOUT.value)

    def test_remote_protocol_error(self):
        """RemoteProtocolError → OTHER_SIDE_CLOSED。"""
        exc = httpx.RemoteProtocolError("peer closed")
        cat, msg = self.probe._classify_exception(exc)
        self.assertEqual(cat, ErrorCategory.OTHER_SIDE_CLOSED.value)

    def test_unknown_exception(self):
        """其他未知异常 → UNKNOWN。"""
        exc = ValueError("something else")
        cat, msg = self.probe._classify_exception(exc)
        self.assertEqual(cat, ErrorCategory.UNKNOWN.value)


# ──────────────────────────────────────────────────────────────────────────
# 路径 B：BaseProbe._infer_unavailable_reason（HTTP 非流式路径）
# ──────────────────────────────────────────────────────────────────────────


class TestInferUnavailableReasonNonStreaming(unittest.TestCase):
    """BaseProbe._infer_unavailable_reason 黄金输出快照（非流式 HTTP）。"""

    def setUp(self):
        self.probe = _make_probe()

    def test_401(self):
        resp = _make_response(401)
        self.assertEqual(
            self.probe._infer_unavailable_reason(resp),
            UnavailableReason.AUTH_FAILED,
        )

    def test_403_discord(self):
        """FreetheAI 签到场景：discord 关键词 → ACCESS_RESTRICTED。"""
        body = '{"error": "daily discord check-in required"}'
        resp = _make_response(403, body)
        self.assertEqual(
            self.probe._infer_unavailable_reason(resp),
            UnavailableReason.ACCESS_RESTRICTED,
        )

    def test_403_checkin(self):
        body = '{"error": "daily check-in required"}'
        resp = _make_response(403, body)
        self.assertEqual(
            self.probe._infer_unavailable_reason(resp),
            UnavailableReason.ACCESS_RESTRICTED,
        )

    def test_403_permission(self):
        body = '{"error": "permission denied"}'
        resp = _make_response(403, body)
        self.assertEqual(
            self.probe._infer_unavailable_reason(resp),
            UnavailableReason.PERMISSION_DENIED,
        )

    def test_403_default(self):
        """403 无关键词兜底 → PERMISSION_DENIED。"""
        resp = _make_response(403, '{"error": "forbidden"}')
        self.assertEqual(
            self.probe._infer_unavailable_reason(resp),
            UnavailableReason.PERMISSION_DENIED,
        )

    def test_404_account_keyword(self):
        """Nvidia 特征：'not found for account' → PERMISSION_DENIED。"""
        body = '{"detail": "Function not found for account"}'
        resp = _make_response(404, body)
        self.assertEqual(
            self.probe._infer_unavailable_reason(resp),
            UnavailableReason.PERMISSION_DENIED,
        )

    def test_404_bare_account_keyword(self):
        """收窄后裸 'account' → MODEL_NOT_FOUND（已修复，不再是 PERMISSION_DENIED）。"""
        body = '{"error": "your account is inactive"}'
        resp = _make_response(404, body)
        result = self.probe._infer_unavailable_reason(resp)
        self.assertEqual(result, UnavailableReason.MODEL_NOT_FOUND)  # 新正确行为

    def test_404_model_not_found(self):
        body = '{"error": "model does not exist"}'
        resp = _make_response(404, body)
        self.assertEqual(
            self.probe._infer_unavailable_reason(resp),
            UnavailableReason.MODEL_NOT_FOUND,
        )

    def test_429(self):
        resp = _make_response(429)
        self.assertEqual(
            self.probe._infer_unavailable_reason(resp),
            UnavailableReason.QUOTA_EXCEEDED,
        )

    def test_402(self):
        resp = _make_response(402)
        self.assertEqual(
            self.probe._infer_unavailable_reason(resp),
            UnavailableReason.PAYMENT_REQUIRED,
        )

    def test_502(self):
        resp = _make_response(502)
        self.assertEqual(
            self.probe._infer_unavailable_reason(resp),
            UnavailableReason.UPSTREAM_ERROR,
        )

    def test_500(self):
        resp = _make_response(500)
        self.assertEqual(
            self.probe._infer_unavailable_reason(resp),
            UnavailableReason.SERVER_ERROR,
        )


# ──────────────────────────────────────────────────────────────────────────
# 路径 C：BaseProbe._infer_error_category_from_status（HTTP → ErrorCategory）
# ──────────────────────────────────────────────────────────────────────────


class TestInferErrorCategoryFromStatus(unittest.TestCase):
    """BaseProbe._infer_error_category_from_status 黄金输出快照。

    [预期 diff] 重构后 502/503/504 将产出 HTTP_UPSTREAM_ERROR（新增），
    500 将产出 HTTP_SERVER_ERROR（新增），而不是 UNKNOWN。
    """

    def setUp(self):
        self.probe = _make_probe()

    def test_401(self):
        self.assertEqual(
            self.probe._infer_error_category_from_status(401),
            ErrorCategory.HTTP_AUTH.value,
        )

    def test_403(self):
        self.assertEqual(
            self.probe._infer_error_category_from_status(403),
            ErrorCategory.HTTP_FORBIDDEN.value,
        )

    def test_404(self):
        self.assertEqual(
            self.probe._infer_error_category_from_status(404),
            ErrorCategory.HTTP_NOT_FOUND.value,
        )

    def test_429(self):
        self.assertEqual(
            self.probe._infer_error_category_from_status(429),
            ErrorCategory.HTTP_RATE_LIMITED.value,
        )

    def test_402(self):
        self.assertEqual(
            self.probe._infer_error_category_from_status(402),
            ErrorCategory.HTTP_PAYMENT_REQUIRED.value,
        )

    def test_502_now_upstream_error(self):
        """502 已修复 → HTTP_UPSTREAM_ERROR。"""
        self.assertEqual(
            self.probe._infer_error_category_from_status(502),
            ErrorCategory.HTTP_UPSTREAM_ERROR.value,
        )

    def test_500_now_server_error(self):
        """500 已修复 → HTTP_SERVER_ERROR。"""
        self.assertEqual(
            self.probe._infer_error_category_from_status(500),
            ErrorCategory.HTTP_SERVER_ERROR.value,
        )


# ──────────────────────────────────────────────────────────────────────────
# 路径 D：BaseProbe._http_status_to_unavailable_reason（流式无 body）
# ──────────────────────────────────────────────────────────────────────────


class TestHttpStatusToUnavailableReason(unittest.TestCase):
    """BaseProbe._http_status_to_unavailable_reason 黄金输出快照（流式路径）。"""

    def setUp(self):
        self.probe = _make_probe()

    def test_401(self):
        self.assertEqual(
            self.probe._http_status_to_unavailable_reason(401),
            UnavailableReason.AUTH_FAILED.value,
        )

    def test_403(self):
        """流式无 body 时 403 只能兜底 PERMISSION_DENIED（物理限制）。"""
        self.assertEqual(
            self.probe._http_status_to_unavailable_reason(403),
            UnavailableReason.PERMISSION_DENIED.value,
        )

    def test_404(self):
        self.assertEqual(
            self.probe._http_status_to_unavailable_reason(404),
            UnavailableReason.MODEL_NOT_FOUND.value,
        )

    def test_429(self):
        self.assertEqual(
            self.probe._http_status_to_unavailable_reason(429),
            UnavailableReason.QUOTA_EXCEEDED.value,
        )

    def test_502(self):
        self.assertEqual(
            self.probe._http_status_to_unavailable_reason(502),
            UnavailableReason.UPSTREAM_ERROR.value,
        )

    def test_500(self):
        self.assertEqual(
            self.probe._http_status_to_unavailable_reason(500),
            UnavailableReason.SERVER_ERROR.value,
        )

    def test_unknown(self):
        self.assertEqual(
            self.probe._http_status_to_unavailable_reason(418),
            UnavailableReason.UNKNOWN.value,
        )


if __name__ == "__main__":
    unittest.main()
