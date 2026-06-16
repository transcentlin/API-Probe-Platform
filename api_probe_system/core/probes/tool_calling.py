"""ToolCallingProbe：工具调用能力探针（M2+ 升级）。

升级点：
    - 网络异常 → BaseProbe._classify_any_exception → ErrorCategory
    - HTTP 错误 → BaseProbe._build_http_error_result
    - 成功路径补充 response_health / first_byte_latency_ms / availability

对应需求：FR-CAP-03
"""
from __future__ import annotations

from ..constants import ModelAvailability, ProbeType
from ..models import CapabilityResult, PlatformConfig
from ..adapters.base import FormatAdapter
from .base import BaseProbe, _AdaptiveTransportError


class ToolCallingProbe(BaseProbe):
    """工具调用探针（FR-CAP-03）。"""

    @property
    def name(self) -> str:
        return "tool_calling"

    @property
    def probe_type(self) -> str:
        return ProbeType.TOOL_CALLING.value

    async def probe(
        self,
        platform: PlatformConfig,
        model: str,
        adapter: FormatAdapter,
        *,
        prefer_streaming: bool = False,
    ) -> CapabilityResult:
        request_body = adapter.build_probe_request(
            prompt="What's the weather like in San Francisco?",
            model=model,
            max_tokens=100,
            temperature=0.7,
        )

        request_body["tools"] = [
            {
                "type": "function",
                "function": {
                    "name": "get_weather",
                    "description": "Get the current weather in a given location",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "location": {
                                "type": "string",
                                "description": "The city and state, e.g. San Francisco, CA",
                            },
                            "unit": {
                                "type": "string",
                                "enum": ["celsius", "fahrenheit"],
                            },
                        },
                        "required": ["location"],
                    },
                },
            }
        ]

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

        message = choices[0].get("message", {})
        tool_calls = message.get("tool_calls", [])

        if not tool_calls:
            content = message.get("content", "")
            return CapabilityResult(
                supported=False,
                reliability="low",
                detail=f"未调用工具，返回文本: {content[:50]}...",
                latency_ms=latency_ms,
                first_byte_latency_ms=fb_latency_ms,
                response_health=health,
                response_mode=response_mode,
                transport_used=transport,
            )

        function_names = [tc.get("function", {}).get("name") for tc in tool_calls]

        if "get_weather" in function_names:
            return CapabilityResult(
                supported=True,
                reliability="high" if health == "healthy" else "medium",
                availability=ModelAvailability.FULLY_AVAILABLE.value,
                detail=f"成功调用工具: {', '.join(function_names)} (健康: {health})",
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
            detail=f"调用了工具但不是预期的: {', '.join(function_names)}",
            latency_ms=latency_ms,
            first_byte_latency_ms=fb_latency_ms,
            response_health=health,
            response_mode=response_mode,
            transport_used=transport,
        )
