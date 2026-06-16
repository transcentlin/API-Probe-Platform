"""MultiTurnProbe：多轮对话能力探针（M2+ 升级）。

升级点：
    - 网络异常 / HTTP 错误使用 BaseProbe helper
    - 成功路径补充 response_health / first_byte_latency_ms / availability

对应需求：FR-CAP-08
"""
from __future__ import annotations

from ..constants import ModelAvailability, ProbeType
from ..models import CapabilityResult, PlatformConfig
from ..adapters.base import FormatAdapter
from .base import BaseProbe, _AdaptiveTransportError


class MultiTurnProbe(BaseProbe):
    """多轮对话探针（FR-CAP-08）。"""

    @property
    def name(self) -> str:
        return "multi_turn"

    @property
    def probe_type(self) -> str:
        return ProbeType.MULTI_TURN.value

    async def probe(
        self,
        platform: PlatformConfig,
        model: str,
        adapter: FormatAdapter,
        *,
        prefer_streaming: bool = False,
    ) -> CapabilityResult:
        messages = [
            {"role": "user", "content": "My favorite color is blue."},
            {"role": "assistant", "content": "That's nice! Blue is a calming color."},
            {"role": "user", "content": "I also like reading books."},
            {"role": "assistant", "content": "Reading is a great hobby!"},
            {"role": "user", "content": "What was my favorite color that I mentioned earlier?"},
        ]

        request_body = {
            "model": model,
            "messages": messages,
            "max_tokens": 50,
            "temperature": 0.0,
        }

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
                detail="响应内容为空",
                latency_ms=latency_ms,
                first_byte_latency_ms=fb_latency_ms,
                response_health=health,
                response_mode=response_mode,
                transport_used=transport,
            )

        content_lower = content.lower()
        mentions_blue = "blue" in content_lower

        forgot = any(
            phrase in content_lower
            for phrase in (
                "don't remember",
                "can't recall",
                "didn't mention",
                "not sure",
                "don't know",
            )
        )

        if mentions_blue and not forgot:
            return CapabilityResult(
                supported=True,
                reliability="high" if health == "healthy" else "medium",
                availability=ModelAvailability.FULLY_AVAILABLE.value,
                detail=f"成功记住上下文: {content[:100]}... (健康: {health})",
                latency_ms=latency_ms,
                first_byte_latency_ms=fb_latency_ms,
                response_health=health,
                response_mode=response_mode,
                transport_used=transport,
            )

        if forgot:
            return CapabilityResult(
                supported=False,
                reliability="high",
                detail=f"模型忘记了上下文: {content[:100]}...",
                latency_ms=latency_ms,
                first_byte_latency_ms=fb_latency_ms,
                response_health=health,
                response_mode=response_mode,
                transport_used=transport,
            )

        return CapabilityResult(
            supported=False,
            reliability="medium",
            detail=f"未能正确回忆上下文: {content[:100]}...",
            latency_ms=latency_ms,
            first_byte_latency_ms=fb_latency_ms,
            response_health=health,
            response_mode=response_mode,
            transport_used=transport,
        )
