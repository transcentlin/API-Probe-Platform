"""StreamingProbe：流式响应能力探针（M2+ 升级）。

升级点（相对 M2 原版）：
    - 复用 BaseProbe._send_streaming_request（返回 dict，含 first_byte_latency_ms）
    - 按 fast/slow 阈值映射 ResponseHealth（HEALTHY / SLUGGISH / DEAD）
    - 网络异常由 BaseProbe._classify_exception 归类到 ErrorCategory
    - HTTP 错误由 BaseProbe._build_http_error_result 处理

对应需求：FR-CAP-02
"""
from __future__ import annotations

from ..constants import ModelAvailability, ProbeType, ResponseHealth
from ..models import CapabilityResult, PlatformConfig
from ..adapters.base import FormatAdapter
from .base import BaseProbe


class StreamingProbe(BaseProbe):
    """流式响应探针（FR-CAP-02）。

    测试策略：
        发送 stream=True 的请求，验证返回的 SSE 流是否合规。

    成功标准（response_mode="streaming"）：
        - HTTP 200
        - 至少收到 1 个 data: 数据块
        - 含 data: [DONE] 结束标记 → reliability=high
        - 缺 [DONE] 标记 → reliability=medium
    """

    @property
    def name(self) -> str:
        return "streaming"

    @property
    def probe_type(self) -> str:
        return ProbeType.STREAMING.value

    async def probe(
        self,
        platform: PlatformConfig,
        model: str,
        adapter: FormatAdapter,
        *,
        prefer_streaming: bool = False,
    ) -> CapabilityResult:
        request_body = adapter.build_probe_request(
            prompt="Count from 1 to 5", model=model, max_tokens=50, temperature=0.7
        )
        request_body["stream"] = True

        try:
            stream_result = await self._send_streaming_request(
                platform, adapter, request_body
            )
        except Exception as e:
            result = self._classify_any_exception(e)
            result.response_mode = "streaming"
            return result

        status_code = stream_result["status_code"]
        if status_code != 200:
            return CapabilityResult(
                supported=False,
                reliability="unknown",
                availability=ModelAvailability.UNAVAILABLE.value,
                unavailable_reason=self._http_status_to_unavailable_reason(status_code),
                error_code=status_code,
                error_category=self._infer_error_category_from_status(status_code),
                error_message=f"流式请求 HTTP {status_code}",
                detail=f"HTTP {status_code}",
                latency_ms=stream_result["total_latency_ms"],
                response_mode="streaming",
            )

        return self._evaluate_stream(stream_result)

    def _evaluate_stream(self, stream_result: dict) -> CapabilityResult:
        """根据收到的 chunks + 首字节延迟综合判定。"""
        chunks = stream_result["chunks"]
        first_byte = stream_result["first_byte_latency_ms"]
        total = stream_result["total_latency_ms"]
        has_done = stream_result["has_done"]

        data_chunks = [c for c in chunks if c != "data: [DONE]"]
        health = self._classify_health(first_byte if first_byte is not None else total)

        if not data_chunks:
            return CapabilityResult(
                supported=False,
                reliability="low",
                availability=ModelAvailability.UNAVAILABLE.value,
                detail="未收到有效数据块",
                latency_ms=total,
                first_byte_latency_ms=first_byte,
                response_health=health,
                response_mode="streaming",
            )

        # 按健康度调整 reliability
        if has_done and len(data_chunks) > 0:
            if health == ResponseHealth.HEALTHY.value:
                reliability = "high"
            elif health == ResponseHealth.SLUGGISH.value:
                reliability = "medium"
            else:
                reliability = "low"
            detail = f"收到 {len(data_chunks)} 个数据块，正常结束 (健康: {health})"
        else:
            # 有数据但缺 [DONE]
            reliability = "medium" if health == ResponseHealth.HEALTHY.value else "low"
            detail = f"收到 {len(data_chunks)} 个数据块，但缺少 [DONE] 标记"

        availability = (
            ModelAvailability.FULLY_AVAILABLE.value
            if health == ResponseHealth.HEALTHY.value and has_done
            else ModelAvailability.PARTIALLY_AVAILABLE.value
        )

        return CapabilityResult(
            supported=True,
            reliability=reliability,
            availability=availability,
            detail=detail,
            latency_ms=total,
            first_byte_latency_ms=first_byte,
            response_health=health,
            response_mode="streaming",
        )
