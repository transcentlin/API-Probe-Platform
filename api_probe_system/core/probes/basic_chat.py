"""BasicChatProbe：基础对话能力探针（M2 核心探针，M2+ 增强）。

判定流程（三段式）：

    1. 非流式请求（超时 = fast_threshold_ms）
       ├─ 成功 → 走 _evaluate_content（含语义检测）
       ├─ HTTP 错误 → 直接返回 _handle_http_error
       ├─ 网络异常 → 进入步骤 2
       └─ 超时（首字节未达）→ 进入步骤 2

    2. 流式 fallback（超时 = slow_threshold_ms，记录首字节延迟）
       ├─ 成功 → 走 _evaluate_content（含语义检测 + 响应分级）
       ├─ HTTP 错误 → 返回 _handle_http_error
       └─ 网络异常 → 用 _classify_exception 归类

    3. _evaluate_content：把内容交给 coherence.assess_coherence
       ├─ coherent → supported=True, reliability 按 response_health 映射
       ├─ suspicious → supported=True, reliability=low
       └─ incoherent → supported=False, error_category=INCOHERENT_RESPONSE

对应需求：FR-CAP-01
"""
from __future__ import annotations

import asyncio
from typing import Optional

import httpx

from ..coherence import assess_coherence
from ..constants import (
    ErrorCategory,
    ModelAvailability,
    ProbeType,
    ResponseHealth,
    UnavailableReason,
    classify_response_health,
)
from ..models import CapabilityResult, PlatformConfig
from ..adapters.base import FormatAdapter
from .base import BaseProbe


class BasicChatProbe(BaseProbe):
    """基础对话探针（FR-CAP-01）。

    增强点（相对 M2 原版）：
        - 非流式 30s 超时后自动尝试流式 fallback（最长 slow_threshold_ms）
        - 记录首字节延迟，按 fast/slow 阈值映射 ResponseHealth
        - 内容通过 coherence.assess_coherence 检测语义崩溃（如 Kimi 乱码）
        - 错误细分到 ErrorCategory（连接失败 / 上游断连 / 读取超时 / 代理拦截）
    """

    @property
    def name(self) -> str:
        return "basic_chat"

    @property
    def probe_type(self) -> str:
        return ProbeType.BASIC_CHAT.value

    async def probe(
        self,
        platform: PlatformConfig,
        model: str,
        adapter: FormatAdapter,
        *,
        prefer_streaming: bool = False,
    ) -> CapabilityResult:
        """探测基础对话能力。

        Args:
            platform: 平台配置
            model: 模型 ID
            adapter: 格式适配器

        Returns:
            CapabilityResult 对象
        """
        # ─── 阶段 1：非流式（超时 = fast_threshold） ───
        non_stream_body = adapter.build_probe_request(
            prompt="Hello", model=model, max_tokens=50, temperature=0.7
        )

        non_stream_result = await self._try_non_streaming(
            platform, adapter, non_stream_body
        )
        if non_stream_result is not None:
            return non_stream_result

        # ─── 阶段 2：流式 fallback（超时 = slow_threshold） ───
        stream_body = adapter.build_probe_request(
            prompt="Hello", model=model, max_tokens=50, temperature=0.7
        )
        stream_body["stream"] = True

        return await self._try_streaming_fallback(platform, adapter, stream_body)

    # ──────────────────────────────────────────────────────────────────
    # 阶段 1：非流式
    # ──────────────────────────────────────────────────────────────────

    async def _try_non_streaming(
        self,
        platform: PlatformConfig,
        adapter: FormatAdapter,
        request_body: dict,
    ) -> Optional[CapabilityResult]:
        """非流式探测。

        Returns:
            CapabilityResult（已得到决定性结果）
            None（应继续到流式 fallback）
        """
        fast_timeout_s = self._timeouts.fast_threshold_ms / 1000.0

        try:
            response, latency_ms = await self._send_request_with_timeout(
                platform, adapter, request_body, total_timeout_s=fast_timeout_s
            )
        except httpx.TimeoutException:
            # 非流式在 fast_threshold 内超时 → fallback 到流式（不返回，让 probe() 走阶段 2）
            return None
        except (httpx.ConnectError, httpx.RemoteProtocolError, httpx.ReadError) as e:
            # 连接级硬错 → 直接报错，无需 fallback
            category, msg = self._classify_exception(e)
            return self._build_network_error_result(
                category, msg, response_mode="non_streaming"
            )
        except Exception as e:
            category, msg = self._classify_exception(e)
            return self._build_network_error_result(
                category, msg, response_mode="non_streaming"
            )

        # 有响应
        if response.status_code == 200:
            parsed = adapter.parse_response(response)
            if parsed.content:
                return self._evaluate_content(
                    content=parsed.content,
                    first_byte_latency_ms=latency_ms,
                    total_latency_ms=latency_ms,
                    response_mode="non_streaming",
                )
            else:
                # 200 但解析失败 / 空响应
                return CapabilityResult(
                    supported=False,
                    reliability="unknown",
                    availability=ModelAvailability.UNAVAILABLE.value,
                    unavailable_reason=UnavailableReason.RESPONSE_INVALID.value,
                    error_code=200,
                    error_category=ErrorCategory.MALFORMED_RESPONSE.value
                    if parsed.error
                    else ErrorCategory.EMPTY_RESPONSE.value,
                    error_message=f"响应解析失败: {parsed.error}" if parsed.error else "响应体为空",
                    response_health=classify_response_health(
                        latency_ms,
                        self._timeouts.fast_threshold_ms,
                        self._timeouts.slow_threshold_ms,
                    ),
                    first_byte_latency_ms=latency_ms,
                    latency_ms=latency_ms,
                    response_mode="non_streaming",
                )
        else:
            return self._build_http_error_result(response, latency_ms, "non_streaming")

    async def _send_request_with_timeout(
        self,
        platform: PlatformConfig,
        adapter: FormatAdapter,
        request_body: dict,
        total_timeout_s: float,
        endpoint: str = "/chat/completions",
    ) -> tuple[httpx.Response, float]:
        """非流式发送，使用指定的总超时（用于阶段 1 的 fast_threshold 限定）。"""
        from ..engine.stages import normalize_base_url
        from ..secret import SecretResolver

        base_url = normalize_base_url(str(platform.base_url))
        api_key = SecretResolver.resolve(platform.api_key)

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

        timeout = httpx.Timeout(total_timeout_s, connect=self._timeouts.connect_timeout_s)
        async with httpx.AsyncClient(timeout=timeout) as client:
            start = asyncio.get_event_loop().time()
            response = await client.post(
                f"{base_url}{endpoint}", json=request_body, headers=headers
            )
            latency_ms = (asyncio.get_event_loop().time() - start) * 1000

        return response, latency_ms

    # ──────────────────────────────────────────────────────────────────
    # 阶段 2：流式 fallback
    # ──────────────────────────────────────────────────────────────────

    async def _try_streaming_fallback(
        self,
        platform: PlatformConfig,
        adapter: FormatAdapter,
        request_body: dict,
    ) -> CapabilityResult:
        """流式 fallback 探测。"""
        try:
            stream_result = await self._send_streaming_request(
                platform, adapter, request_body
            )
        except (httpx.TimeoutException, httpx.ConnectError,
                httpx.RemoteProtocolError, httpx.ReadError) as e:
            category, msg = self._classify_exception(e)
            return self._build_network_error_result(
                category, msg, response_mode="streaming_fallback"
            )
        except Exception as e:
            category, msg = self._classify_exception(e)
            return self._build_network_error_result(
                category, msg, response_mode="streaming_fallback"
            )

        status_code = stream_result["status_code"]
        if status_code != 200:
            # 流式 HTTP 错误：无法用 response.json()，构造一个最小占位
            return CapabilityResult(
                supported=False,
                reliability="unknown",
                availability=ModelAvailability.UNAVAILABLE.value,
                unavailable_reason=self._http_status_to_unavailable_reason(status_code),
                error_code=status_code,
                error_category=self._infer_error_category_from_status(status_code),
                error_message=f"流式请求 HTTP {status_code}",
                response_mode="streaming_fallback",
                latency_ms=stream_result["total_latency_ms"],
            )

        # 流式成功（HTTP 200）
        content = stream_result["content"]
        first_byte = stream_result["first_byte_latency_ms"]
        total = stream_result["total_latency_ms"]

        if not content:
            return CapabilityResult(
                supported=False,
                reliability="unknown",
                availability=ModelAvailability.UNAVAILABLE.value,
                unavailable_reason=UnavailableReason.RESPONSE_INVALID.value,
                error_code=200,
                error_category=ErrorCategory.EMPTY_RESPONSE.value,
                error_message="流式响应未拼接出任何 content",
                response_health=classify_response_health(
                    first_byte,
                    self._timeouts.fast_threshold_ms,
                    self._timeouts.slow_threshold_ms,
                ),
                first_byte_latency_ms=first_byte,
                latency_ms=total,
                response_mode="streaming_fallback",
            )

        return self._evaluate_content(
            content=content,
            first_byte_latency_ms=first_byte,
            total_latency_ms=total,
            response_mode="streaming_fallback",
        )

    # ──────────────────────────────────────────────────────────────────
    # 阶段 3：内容评估（语义连贯性 + 响应分级）
    # ──────────────────────────────────────────────────────────────────

    def _evaluate_content(
        self,
        content: str,
        first_byte_latency_ms: float,
        total_latency_ms: float,
        response_mode: str,
    ) -> CapabilityResult:
        """根据响应分级 + 内容质量综合判定。"""
        quality, reason = assess_coherence(content)
        health = classify_response_health(
            first_byte_latency_ms,
            self._timeouts.fast_threshold_ms,
            self._timeouts.slow_threshold_ms,
        )

        if quality == "incoherent":
            return CapabilityResult(
                supported=False,
                reliability="unknown",
                availability=ModelAvailability.UNAVAILABLE.value,
                unavailable_reason=UnavailableReason.RESPONSE_INCOHERENT.value,
                error_code=200,
                error_category=ErrorCategory.INCOHERENT_RESPONSE.value,
                error_message=f"响应内容语义崩溃: {reason}",
                detail=f"响应（截断）: {content[:80]}",
                response_health=health,
                first_byte_latency_ms=first_byte_latency_ms,
                latency_ms=total_latency_ms,
                response_mode=response_mode,
            )

        # coherent 或 suspicious 都视为 supported=True，但 reliability 不同
        if health == ResponseHealth.HEALTHY.value:
            reliability = "high" if quality == "coherent" else "medium"
        elif health == ResponseHealth.SLUGGISH.value:
            reliability = "medium" if quality == "coherent" else "low"
        else:
            # DEAD 不应在此走到（理论上 incoherent 才会触发），保险给 low
            reliability = "low"

        availability = (
            ModelAvailability.FULLY_AVAILABLE.value
            if health == ResponseHealth.HEALTHY.value and quality == "coherent"
            else ModelAvailability.PARTIALLY_AVAILABLE.value
        )

        detail_prefix = "" if response_mode == "non_streaming" else "[流式 fallback] "
        return CapabilityResult(
            supported=True,
            reliability=reliability,
            availability=availability,
            detail=f"{detail_prefix}响应: {content[:50]}... (质量: {quality}, 健康: {health})",
            response_health=health,
            first_byte_latency_ms=first_byte_latency_ms,
            latency_ms=total_latency_ms,
            response_mode=response_mode,
        )

    # 辅助方法 _build_network_error_result / _build_http_error_result /
    # _http_status_to_unavailable_reason 已上移至 BaseProbe，本类直接继承。
