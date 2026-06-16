"""JsonModeProbe：JSON 模式能力探针（M2+ 升级）。

升级点：
    - 网络异常 / HTTP 错误使用 BaseProbe helper
    - 成功路径补充 response_health / first_byte_latency_ms / availability
    - JSON 解析失败明确标 MALFORMED_RESPONSE（细分类）

对应需求：FR-CAP-05
"""
from __future__ import annotations

import json

from ..constants import ErrorCategory, ModelAvailability, ProbeType, UnavailableReason
from ..models import CapabilityResult, PlatformConfig
from ..adapters.base import FormatAdapter
from .base import BaseProbe, _AdaptiveTransportError


class JsonModeProbe(BaseProbe):
    """JSON 模式探针（FR-CAP-05）。"""

    @property
    def name(self) -> str:
        return "json_mode"

    @property
    def probe_type(self) -> str:
        return ProbeType.JSON_MODE.value

    async def probe(
        self,
        platform: PlatformConfig,
        model: str,
        adapter: FormatAdapter,
        *,
        prefer_streaming: bool = False,
    ) -> CapabilityResult:
        request_body = adapter.build_probe_request(
            prompt='Generate a JSON object with user information: {"name": "John", "age": 30, "city": "New York"}',
            model=model,
            max_tokens=100,
            temperature=0.7,
        )
        request_body["response_format"] = {"type": "json_object"}

        try:
            data, latency_ms, fb_latency_ms, transport = await self._send_and_parse(
                platform,
                model,
                adapter,
                request_body,
                prefer_streaming=prefer_streaming,
            )
        except _AdaptiveTransportError as e:
            return e.result
        except Exception as e:
            return self._classify_any_exception(e)

        return self._evaluate_data(data, latency_ms, fb_latency_ms, transport)

    def _evaluate_data(
        self,
        data: dict,
        latency_ms: float,
        fb_latency_ms: float | None,
        transport: str,
    ) -> CapabilityResult:
        """评估解析后的响应数据（非流式和流式统一入口）。"""
        health = self._classify_health(fb_latency_ms or latency_ms)
        response_mode = "streaming" if transport == "streaming" else "non_streaming"

        choices = data.get("choices", [])
        if not choices:
            return CapabilityResult(
                supported=False,
                reliability="low",
                detail="响应中没有 choices 字段",
                latency_ms=latency_ms,
                first_byte_latency_ms=fb_latency_ms,
                response_health=health,
                response_mode=response_mode,
                transport_used=transport,
            )

        content = choices[0].get("message", {}).get("content", "")
        if not content:
            return CapabilityResult(
                supported=False,
                reliability="low",
                availability=ModelAvailability.UNAVAILABLE.value,
                unavailable_reason=UnavailableReason.RESPONSE_INVALID.value,
                error_category=ErrorCategory.EMPTY_RESPONSE.value,
                detail="响应内容为空",
                latency_ms=latency_ms,
                first_byte_latency_ms=fb_latency_ms,
                response_health=health,
                response_mode=response_mode,
                transport_used=transport,
            )

        try:
            parsed_json = json.loads(content)
        except json.JSONDecodeError as e:
            return CapabilityResult(
                supported=False,
                reliability="low",
                availability=ModelAvailability.UNAVAILABLE.value,
                unavailable_reason=UnavailableReason.RESPONSE_INVALID.value,
                error_category=ErrorCategory.MALFORMED_RESPONSE.value,
                detail=f"响应不是有效 JSON: {e}, 内容: {content[:100]}...",
                latency_ms=latency_ms,
                first_byte_latency_ms=fb_latency_ms,
                response_health=health,
                response_mode=response_mode,
                transport_used=transport,
            )

        if isinstance(parsed_json, dict):
            return CapabilityResult(
                supported=True,
                reliability="high" if health == "healthy" else "medium",
                availability=ModelAvailability.FULLY_AVAILABLE.value,
                detail=f"成功返回 JSON 对象，包含 {len(parsed_json)} 个字段 (健康: {health})",
                latency_ms=latency_ms,
                first_byte_latency_ms=fb_latency_ms,
                response_health=health,
                response_mode=response_mode,
                transport_used=transport,
            )

        return CapabilityResult(
            supported=True,
            reliability="medium",
            availability=ModelAvailability.PARTIALLY_AVAILABLE.value,
            detail=f"返回了 JSON 但不是对象: {type(parsed_json).__name__}",
            latency_ms=latency_ms,
            first_byte_latency_ms=fb_latency_ms,
            response_health=health,
            response_mode=response_mode,
            transport_used=transport,
        )
