"""ReasoningProbe：推理能力探针（M2+ 升级）。

升级点：
    - 网络异常 / HTTP 错误使用 BaseProbe helper
    - 成功路径补充 response_health / first_byte_latency_ms / availability

对应需求：FR-CAP-06
"""
from __future__ import annotations

from ..constants import ModelAvailability, ProbeType
from ..models import CapabilityResult, PlatformConfig
from ..adapters.base import FormatAdapter
from .base import BaseProbe, _AdaptiveTransportError


class ReasoningProbe(BaseProbe):
    """推理能力探针（FR-CAP-06）。"""

    TEST_QUESTION = (
        "There are chickens and rabbits in a cage. "
        "There are 8 heads and 22 legs in total. "
        "How many chickens and how many rabbits are there? "
        "Please provide the answer in the format: X chickens and Y rabbits."
    )

    @property
    def name(self) -> str:
        return "reasoning"

    @property
    def probe_type(self) -> str:
        return ProbeType.REASONING.value

    async def probe(
        self,
        platform: PlatformConfig,
        model: str,
        adapter: FormatAdapter,
        *,
        prefer_streaming: bool = False,
    ) -> CapabilityResult:
        request_body = adapter.build_probe_request(
            prompt=self.TEST_QUESTION,
            model=model,
            max_tokens=200,
            temperature=0.0,
        )

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
        mentions_5 = "5" in content or "five" in content_lower
        mentions_3 = "3" in content or "three" in content_lower
        mentions_chickens = "chicken" in content_lower
        mentions_rabbits = "rabbit" in content_lower

        if mentions_5 and mentions_3 and mentions_chickens and mentions_rabbits:
            return CapabilityResult(
                supported=True,
                reliability="high" if health == "healthy" else "medium",
                availability=ModelAvailability.FULLY_AVAILABLE.value,
                detail=f"推理正确: {content[:100]}... (健康: {health})",
                latency_ms=latency_ms,
                first_byte_latency_ms=fb_latency_ms,
                response_health=health,
                response_mode=response_mode,
                transport_used=transport,
            )

        if mentions_chickens and mentions_rabbits:
            return CapabilityResult(
                supported=True,
                reliability="medium",
                availability=ModelAvailability.PARTIALLY_AVAILABLE.value,
                detail=f"理解问题但答案可能不正确: {content[:100]}...",
                latency_ms=latency_ms,
                first_byte_latency_ms=fb_latency_ms,
                response_health=health,
                response_mode=response_mode,
                transport_used=transport,
            )

        return CapabilityResult(
            supported=False,
            reliability="low",
            detail=f"未能正确理解问题: {content[:100]}...",
            latency_ms=latency_ms,
            first_byte_latency_ms=fb_latency_ms,
            response_health=health,
            response_mode=response_mode,
            transport_used=transport,
        )
