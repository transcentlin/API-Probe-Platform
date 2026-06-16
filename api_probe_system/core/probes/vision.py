"""VisionProbe：视觉理解能力探针（M2+ 升级）。

升级点：
    - 网络异常 / HTTP 错误使用 BaseProbe helper
    - 成功路径补充 response_health / first_byte_latency_ms / availability

对应需求：FR-CAP-04
"""
from __future__ import annotations

from ..constants import ModelAvailability, ProbeType
from ..models import CapabilityResult, PlatformConfig
from ..adapters.base import FormatAdapter
from .base import BaseProbe, _AdaptiveTransportError


class VisionProbe(BaseProbe):
    """视觉理解探针（FR-CAP-04）。"""

    # 测试图像：红色圆形 SVG（base64）
    TEST_IMAGE_BASE64 = (
        "data:image/svg+xml;base64,PHN2ZyB3aWR0aD0iMTAwIiBoZWlnaHQ9IjEwMCIgeG1sbnM9Imh0dHA6Ly93d3cudzMub3JnLzIwMDAvc3ZnIj4KICA8Y2lyY2xlIGN4PSI1MCIgY3k9IjUwIiByPSI0MCIgZmlsbD0icmVkIiAvPgo8L3N2Zz4="
    )

    @property
    def name(self) -> str:
        return "vision"

    @property
    def probe_type(self) -> str:
        return ProbeType.VISION.value

    async def probe(
        self,
        platform: PlatformConfig,
        model: str,
        adapter: FormatAdapter,
        *,
        prefer_streaming: bool = False,
    ) -> CapabilityResult:
        request_body = {
            "model": model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": "What do you see in this image? Describe the color and shape.",
                        },
                        {
                            "type": "image_url",
                            "image_url": {"url": self.TEST_IMAGE_BASE64},
                        },
                    ],
                }
            ],
            "max_tokens": 100,
            "temperature": 0.7,
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
        mentions_color = any(
            kw in content_lower for kw in ("red", "circle", "round", "shape", "color")
        )

        if mentions_color:
            return CapabilityResult(
                supported=True,
                reliability="high" if health == "healthy" else "medium",
                availability=ModelAvailability.FULLY_AVAILABLE.value,
                detail=f"成功识别图像: {content[:100]}... (健康: {health})",
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
            detail=f"返回了响应但可能未理解图像: {content[:100]}...",
            latency_ms=latency_ms,
            first_byte_latency_ms=fb_latency_ms,
            response_health=health,
            response_mode=response_mode,
            transport_used=transport,
        )
