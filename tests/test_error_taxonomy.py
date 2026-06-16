"""Step 1+2：error_taxonomy 规则表完整性测试 + 一致性桥接测试。

测试覆盖：
    - 规则顺序敏感性（ConnectTimeout 在 TimeoutException 前）
    - 403 带关键词规则在 403 兜底前
    - proxy_blocked AND 语义
    - 每条规则可达性验证
    - classify() 输出与旧分类函数快照一致（除预期 diff 外）
"""
from __future__ import annotations

import sys
import os
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import httpx

from api_probe_system.core.constants import ErrorCategory, UnavailableReason
from api_probe_system.core.error_taxonomy import (
    classify,
    ErrorSignal,
    Diagnosis,
    CLASSIFICATION_RULES,
    signal_from_exception,
    signal_from_response,
)
from api_probe_system.core.probes.base import BaseProbe
from api_probe_system.core.models import ProbeTimeouts
from unittest.mock import MagicMock
import json as _json


def _probe() -> BaseProbe:
    return BaseProbe(ProbeTimeouts(fast_threshold_ms=30000, slow_threshold_ms=60000, connect_timeout_s=10.0))


def _resp(status: int, body: str = "") -> httpx.Response:
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status
    resp.text = body
    try:
        resp.json.return_value = _json.loads(body)
    except Exception:
        resp.json.side_effect = Exception("not json")
    return resp


# ──────────────────────────────────────────────────────────────────────────
# 规则顺序敏感性
# ──────────────────────────────────────────────────────────────────────────


class TestRuleOrdering(unittest.TestCase):
    """验证规则表中顺序敏感的规则排列正确。"""

    def _find_first_index(self, exc_type: type) -> int:
        """在规则表中找到第一条匹配该异常类型的规则索引。"""
        for i, rule in enumerate(CLASSIFICATION_RULES):
            if exc_type in rule.exception_types:
                return i
        return -1

    def test_connect_timeout_before_timeout_exception(self):
        """ConnectTimeout 是 TimeoutException 子类，必须排在 TimeoutException 之前。"""
        idx_connect_timeout = self._find_first_index(httpx.ConnectTimeout)
        idx_timeout = self._find_first_index(httpx.TimeoutException)
        self.assertGreater(idx_timeout, idx_connect_timeout,
            "ConnectTimeout 规则必须在 TimeoutException 规则之前")

    def test_proxy_blocked_before_connect_error(self):
        """代理拦截规则（需要 AND 关键词）必须在普通 ConnectError 规则之前。"""
        proxy_idx = -1
        connect_err_idx = -1
        for i, rule in enumerate(CLASSIFICATION_RULES):
            if rule.category == ErrorCategory.PROXY_BLOCKED.value:
                proxy_idx = i
                break
        for i, rule in enumerate(CLASSIFICATION_RULES):
            if (httpx.ConnectError in rule.exception_types
                    and rule.category == ErrorCategory.CONNECT_FAILED.value):
                connect_err_idx = i
                break
        self.assertGreater(connect_err_idx, proxy_idx,
            "PROXY_BLOCKED 规则必须在普通 ConnectError 规则之前")

    def test_403_keyword_rule_before_403_fallback(self):
        """403 带关键词规则必须在 403 纯兜底之前。"""
        keyword_idx = -1
        fallback_idx = -1
        for i, rule in enumerate(CLASSIFICATION_RULES):
            if 403 in rule.status_codes:
                if rule.body_keywords and keyword_idx == -1:
                    keyword_idx = i
                if not rule.body_keywords and not rule.platforms:
                    fallback_idx = i  # 最后一个无关键词的 403 规则
        self.assertNotEqual(keyword_idx, -1, "应有 403 带关键词规则")
        self.assertNotEqual(fallback_idx, -1, "应有 403 兜底规则")
        self.assertLess(keyword_idx, fallback_idx, "403 关键词规则必须在 403 兜底之前")

    def test_404_account_phrase_before_404_fallback(self):
        """404 精确短语（not found for account）规则必须在 404 兜底之前。"""
        phrase_idx = -1
        fallback_idx = -1
        for i, rule in enumerate(CLASSIFICATION_RULES):
            if 404 in rule.status_codes and not rule.platforms:
                if "not found for account" in rule.body_keywords:
                    phrase_idx = i
                elif not rule.body_keywords:
                    fallback_idx = i
        self.assertLess(phrase_idx, fallback_idx,
            "404 精确短语规则必须在 404 兜底之前")

    def test_5xx_upstream_before_server_error(self):
        """502/503/504 规则必须在通用 5xx 范围规则之前。"""
        upstream_idx = -1
        server_idx = -1
        for i, rule in enumerate(CLASSIFICATION_RULES):
            if rule.category == ErrorCategory.HTTP_UPSTREAM_ERROR.value and upstream_idx == -1:
                upstream_idx = i
            if rule.category == ErrorCategory.HTTP_SERVER_ERROR.value and server_idx == -1:
                server_idx = i
        self.assertLess(upstream_idx, server_idx,
            "HTTP_UPSTREAM_ERROR 规则必须在 HTTP_SERVER_ERROR 前")


# ──────────────────────────────────────────────────────────────────────────
# classify() 核心分类行为
# ──────────────────────────────────────────────────────────────────────────


class TestClassifyExceptions(unittest.TestCase):
    """异常信号的分类行为。"""

    def test_proxy_blocked_and_keywords(self):
        """AND 语义：两个关键词都有才归 PROXY_BLOCKED。"""
        exc = httpx.ConnectError("Access denied by network settings")
        sig = signal_from_exception(exc)
        result = classify(sig)
        self.assertEqual(result.error_category, ErrorCategory.PROXY_BLOCKED.value)
        self.assertEqual(result.unavailable_reason, UnavailableReason.NETWORK_ERROR.value)

    def test_proxy_blocked_only_one_keyword(self):
        """只有 'access denied' → 不归 PROXY_BLOCKED（AND 未满足）。"""
        exc = httpx.ConnectError("Access denied by something else")
        sig = signal_from_exception(exc)
        result = classify(sig)
        self.assertNotEqual(result.error_category, ErrorCategory.PROXY_BLOCKED.value)

    def test_connect_timeout(self):
        exc = httpx.ConnectTimeout("timeout")
        sig = signal_from_exception(exc)
        result = classify(sig)
        self.assertEqual(result.error_category, ErrorCategory.CONNECT_FAILED.value)

    def test_connect_error(self):
        exc = httpx.ConnectError("connection refused")
        sig = signal_from_exception(exc)
        result = classify(sig)
        self.assertEqual(result.error_category, ErrorCategory.CONNECT_FAILED.value)

    def test_read_timeout(self):
        exc = httpx.ReadTimeout("read timeout")
        sig = signal_from_exception(exc)
        result = classify(sig)
        self.assertEqual(result.error_category, ErrorCategory.READ_TIMEOUT.value)

    def test_remote_protocol_error(self):
        exc = httpx.RemoteProtocolError("peer closed")
        sig = signal_from_exception(exc)
        result = classify(sig)
        self.assertEqual(result.error_category, ErrorCategory.OTHER_SIDE_CLOSED.value)

    def test_unknown_exception(self):
        exc = ValueError("something weird")
        sig = signal_from_exception(exc)
        result = classify(sig)
        self.assertEqual(result.error_category, ErrorCategory.UNKNOWN.value)
        self.assertEqual(result.unavailable_reason, UnavailableReason.UNKNOWN.value)


class TestClassifyHttpStatus(unittest.TestCase):
    """HTTP 状态码信号的分类行为。"""

    def _sig(self, status: int, body: str = "", platform: str | None = None) -> ErrorSignal:
        try:
            parsed = _json.loads(body)
            body_text = str(parsed).lower()
        except Exception:
            body_text = body.lower()
        return ErrorSignal(
            status_code=status,
            body_text=body_text,
            platform_name=platform,
        )

    def test_401(self):
        result = classify(self._sig(401))
        self.assertEqual(result.error_category, ErrorCategory.HTTP_AUTH.value)
        self.assertEqual(result.unavailable_reason, UnavailableReason.AUTH_FAILED.value)

    def test_403_discord(self):
        result = classify(self._sig(403, '{"error":"daily discord check-in required"}'))
        self.assertEqual(result.unavailable_reason, UnavailableReason.ACCESS_RESTRICTED.value)

    def test_403_checkin(self):
        result = classify(self._sig(403, '{"error":"daily check-in required"}'))
        self.assertEqual(result.unavailable_reason, UnavailableReason.ACCESS_RESTRICTED.value)

    def test_403_payment(self):
        result = classify(self._sig(403, '{"error":"payment required to access this model"}'))
        self.assertEqual(result.unavailable_reason, UnavailableReason.PAYMENT_REQUIRED.value)

    def test_403_fallback(self):
        result = classify(self._sig(403, '{"error":"forbidden"}'))
        self.assertEqual(result.unavailable_reason, UnavailableReason.PERMISSION_DENIED.value)

    def test_403_freetheai_platform_specific(self):
        result = classify(self._sig(403, '{"error":"discord check-in required"}', platform="freetheai"))
        self.assertEqual(result.unavailable_reason, UnavailableReason.ACCESS_RESTRICTED.value)

    def test_404_not_found_for_account(self):
        result = classify(self._sig(404, '{"detail":"Function not found for account"}'))
        self.assertEqual(result.unavailable_reason, UnavailableReason.PERMISSION_DENIED.value)

    def test_404_bare_account_becomes_model_not_found(self):
        """[预期 diff] 收窄后裸 'account' 不再 → PERMISSION_DENIED，改为 MODEL_NOT_FOUND。"""
        result = classify(self._sig(404, '{"error":"your account is inactive"}'))
        self.assertEqual(result.unavailable_reason, UnavailableReason.MODEL_NOT_FOUND.value)

    def test_404_model_not_found(self):
        result = classify(self._sig(404, '{"error":"model does not exist"}'))
        self.assertEqual(result.unavailable_reason, UnavailableReason.MODEL_NOT_FOUND.value)

    def test_429(self):
        result = classify(self._sig(429))
        self.assertEqual(result.error_category, ErrorCategory.HTTP_RATE_LIMITED.value)
        self.assertEqual(result.unavailable_reason, UnavailableReason.QUOTA_EXCEEDED.value)

    def test_402(self):
        result = classify(self._sig(402))
        self.assertEqual(result.error_category, ErrorCategory.HTTP_PAYMENT_REQUIRED.value)
        self.assertEqual(result.unavailable_reason, UnavailableReason.PAYMENT_REQUIRED.value)

    def test_502_now_upstream_error(self):
        """[修复 bug] 502 现在产出 HTTP_UPSTREAM_ERROR（旧行为是 UNKNOWN）。"""
        result = classify(self._sig(502))
        self.assertEqual(result.error_category, ErrorCategory.HTTP_UPSTREAM_ERROR.value)
        self.assertEqual(result.unavailable_reason, UnavailableReason.UPSTREAM_ERROR.value)

    def test_503_upstream_error(self):
        result = classify(self._sig(503))
        self.assertEqual(result.error_category, ErrorCategory.HTTP_UPSTREAM_ERROR.value)

    def test_500_now_server_error(self):
        """[修复 bug] 500 现在产出 HTTP_SERVER_ERROR（旧行为是 UNKNOWN）。"""
        result = classify(self._sig(500))
        self.assertEqual(result.error_category, ErrorCategory.HTTP_SERVER_ERROR.value)
        self.assertEqual(result.unavailable_reason, UnavailableReason.SERVER_ERROR.value)

    def test_400(self):
        result = classify(self._sig(400))
        self.assertEqual(result.error_category, ErrorCategory.MALFORMED_RESPONSE.value)
        self.assertEqual(result.unavailable_reason, UnavailableReason.RESPONSE_INVALID.value)


class TestClassifyAppSignal(unittest.TestCase):
    """应用层信号优先于 HTTP 状态码。"""

    def test_empty_signal_overrides_status(self):
        sig = ErrorSignal(status_code=200, app_signal="empty")
        result = classify(sig)
        self.assertEqual(result.error_category, ErrorCategory.EMPTY_RESPONSE.value)

    def test_malformed_signal(self):
        sig = ErrorSignal(status_code=200, app_signal="malformed")
        result = classify(sig)
        self.assertEqual(result.error_category, ErrorCategory.MALFORMED_RESPONSE.value)

    def test_incoherent_signal(self):
        sig = ErrorSignal(status_code=200, app_signal="incoherent")
        result = classify(sig)
        self.assertEqual(result.error_category, ErrorCategory.INCOHERENT_RESPONSE.value)
        self.assertEqual(result.unavailable_reason, UnavailableReason.RESPONSE_INCOHERENT.value)


class TestClassifyNativeStatus(unittest.TestCase):
    """平台 native_status 字段分类。"""

    def test_native_dead(self):
        sig = ErrorSignal(native_status="dead")
        result = classify(sig)
        self.assertEqual(result.unavailable_reason, UnavailableReason.PLATFORM_DEAD.value)

    def test_native_offline(self):
        sig = ErrorSignal(native_status="offline")
        result = classify(sig)
        self.assertEqual(result.unavailable_reason, UnavailableReason.PLATFORM_DEAD.value)


# ──────────────────────────────────────────────────────────────────────────
# 一致性桥接：classify() 输出 vs 旧分类函数快照
# ──────────────────────────────────────────────────────────────────────────


class TestConsistencyWithBaseline(unittest.TestCase):
    """classify() 与旧路径快照对比。

    除 [预期 diff] 外，所有 case 必须与 Step 0 基线一致。
    """

    def setUp(self):
        self.probe = _probe()

    def _classify_new(self, status: int, body: str = "", platform: str | None = None) -> Diagnosis:
        resp = _resp(status, body)
        sig = signal_from_response(resp, platform_name=platform)
        return classify(sig)

    def test_401_consistent(self):
        old_reason = self.probe._infer_unavailable_reason(_resp(401))
        new = self._classify_new(401)
        self.assertEqual(new.unavailable_reason, old_reason.value)
        self.assertEqual(new.error_category, ErrorCategory.HTTP_AUTH.value)

    def test_403_discord_consistent(self):
        body = '{"error": "daily discord check-in required"}'
        old_reason = self.probe._infer_unavailable_reason(_resp(403, body))
        new = self._classify_new(403, body)
        self.assertEqual(new.unavailable_reason, old_reason.value)

    def test_403_default_consistent(self):
        body = '{"error": "forbidden"}'
        old_reason = self.probe._infer_unavailable_reason(_resp(403, body))
        new = self._classify_new(403, body)
        self.assertEqual(new.unavailable_reason, old_reason.value)

    def test_404_not_found_for_account_consistent(self):
        body = '{"detail": "Function not found for account"}'
        old_reason = self.probe._infer_unavailable_reason(_resp(404, body))
        new = self._classify_new(404, body)
        self.assertEqual(new.unavailable_reason, old_reason.value)

    def test_404_model_not_found_consistent(self):
        body = '{"error": "model does not exist"}'
        old_reason = self.probe._infer_unavailable_reason(_resp(404, body))
        new = self._classify_new(404, body)
        self.assertEqual(new.unavailable_reason, old_reason.value)

    def test_429_consistent(self):
        old_reason = self.probe._infer_unavailable_reason(_resp(429))
        new = self._classify_new(429)
        self.assertEqual(new.unavailable_reason, old_reason.value)

    def test_402_consistent(self):
        old_reason = self.probe._infer_unavailable_reason(_resp(402))
        new = self._classify_new(402)
        self.assertEqual(new.unavailable_reason, old_reason.value)

    def test_502_reason_consistent(self):
        """502 的 reason 一致（都是 UPSTREAM_ERROR）；category 是预期 diff（UNKNOWN → HTTP_UPSTREAM_ERROR）。"""
        old_reason = self.probe._infer_unavailable_reason(_resp(502))
        new = self._classify_new(502)
        self.assertEqual(new.unavailable_reason, old_reason.value)  # reason 一致
        # category 是有意改进（不用断言旧值）

    def test_500_reason_consistent(self):
        """500 的 reason 一致；category 是预期 diff。"""
        old_reason = self.probe._infer_unavailable_reason(_resp(500))
        new = self._classify_new(500)
        self.assertEqual(new.unavailable_reason, old_reason.value)

    def test_404_bare_account_model_not_found(self):
        """裸 account 收窄后两条路径输出一致：MODEL_NOT_FOUND。"""
        body = '{"error": "your account is inactive"}'
        old_reason = self.probe._infer_unavailable_reason(_resp(404, body))
        new = self._classify_new(404, body)
        # 两条路径现在一致（都走 taxonomy）
        self.assertEqual(old_reason.value, UnavailableReason.MODEL_NOT_FOUND.value)
        self.assertEqual(new.unavailable_reason, UnavailableReason.MODEL_NOT_FOUND.value)

    def test_exception_connect_timeout_consistent(self):
        """ConnectTimeout 异常分类一致性。"""
        exc = httpx.ConnectTimeout("timeout")
        old_cat, _ = self.probe._classify_exception(exc)
        new = classify(signal_from_exception(exc))
        self.assertEqual(new.error_category, old_cat)

    def test_exception_read_timeout_consistent(self):
        exc = httpx.ReadTimeout("read timeout")
        old_cat, _ = self.probe._classify_exception(exc)
        new = classify(signal_from_exception(exc))
        self.assertEqual(new.error_category, old_cat)

    def test_exception_remote_protocol_consistent(self):
        exc = httpx.RemoteProtocolError("peer closed")
        old_cat, _ = self.probe._classify_exception(exc)
        new = classify(signal_from_exception(exc))
        self.assertEqual(new.error_category, old_cat)

    def test_exception_proxy_blocked_consistent(self):
        exc = httpx.ConnectError("Access denied by network settings")
        old_cat, _ = self.probe._classify_exception(exc)
        new = classify(signal_from_exception(exc))
        self.assertEqual(new.error_category, old_cat)


if __name__ == "__main__":
    unittest.main()
