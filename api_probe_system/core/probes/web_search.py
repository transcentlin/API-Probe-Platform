"""WebSearchProbe：联网搜索能力探针（M2+ 升级）。

升级点：
    - 网络异常 / HTTP 错误使用 BaseProbe helper
    - 成功路径补充 response_health / first_byte_latency_ms / availability

对应需求：FR-CAP-07
"""
from __future__ import annotations

from datetime import datetime

from ..constants import ModelAvailability, ProbeType
from ..models import CapabilityResult, PlatformConfig
from ..adapters.base import FormatAdapter
from .base import BaseProbe, _AdaptiveTransportError


class WebSearchProbe(BaseProbe):
    """联网搜索探针（FR-CAP-07）。"""

    @property
    def name(self) -> str:
        return "web_search"

    @property
    def probe_type(self) -> str:
        return ProbeType.WEB_SEARCH.value

    async def probe(
        self,
        platform: PlatformConfig,
        model: str,
        adapter: FormatAdapter,
        *,
        prefer_streaming: bool = False,
    ) -> CapabilityResult:
        now = datetime.now()
        current_year = now.year
        current_month = now.strftime("%B")

        request_body = adapter.build_probe_request(
            prompt="What is today's date? Please provide the current year, month, and day.",
            model=model,
            max_tokens=100,
            temperature=0.7,
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

        return self._evaluate_data(
            data, latency_ms, fb_latency_ms, transport, current_year, current_month
        )

    def _evaluate_data(
        self,
        data: dict,
        latency_ms: float,
        fb_latency_ms: float | None,
        transport: str,
        current_year: int,
        current_month: str,
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
        mentions_year = str(current_year) in content
        mentions_month = current_month.lower() in content_lower

        cannot_access = any(
            phrase in content_lower
            for phrase in (
                "cannot access",
                "don't have access",
                "no access to",
                "unable to access",
                "can't browse",
                "knowledge cutoff",
                "training data",
            )
        )

        if cannot_access:
            return CapabilityResult(
                supported=False,
                reliability="high",
                detail=f"模型明确表示无法联网: {content[:100]}...",
                latency_ms=latency_ms,
                first_byte_latency_ms=fb_latency_ms,
                response_health=health,
                response_mode=response_mode,
                transport_used=transport,
            )

        if mentions_year and mentions_month:
            return CapabilityResult(
                supported=True,
                reliability="high" if health == "healthy" else "medium",
                availability=ModelAvailability.FULLY_AVAILABLE.value,
                detail=f"成功返回实时信息: {content[:100]}... (健康: {health})",
                latency_ms=latency_ms,
                first_byte_latency_ms=fb_latency_ms,
                response_health=health,
                response_mode=response_mode,
                transport_used=transport,
            )

        if mentions_year or mentions_month:
            return CapabilityResult(
                supported=True,
                reliability="medium",
                availability=ModelAvailability.PARTIALLY_AVAILABLE.value,
                detail=f"返回了部分实时信息: {content[:100]}...",
                latency_ms=latency_ms,
                first_byte_latency_ms=fb_latency_ms,
                response_health=health,
                response_mode=response_mode,
                transport_used=transport,
            )

        return CapabilityResult(
            supported=False,
            reliability="low",
            detail=f"未返回实时信息: {content[:100]}...",
            latency_ms=latency_ms,
            first_byte_latency_ms=fb_latency_ms,
            response_health=health,
            response_mode=response_mode,
            transport_used=transport,
        )
