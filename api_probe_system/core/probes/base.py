# 修改历史 (Revision History)
# ==================================
# 版本: v1.4
# 日期: 2026-06-15
# 修改说明: 在 _send_request 和 _send_streaming_request 中引入格式适配器（FormatAdapter）自适应 Header 与 Endpoint 的逻辑，打通多 API 协议的自适应测试。
# ==================================
# 版本: v1.3
# 日期: 2026-06-15
# 修改说明: 在 _build_http_error_result 中检测 HTTP 429 并提取其 Retry-After 重试秒数，写入 CapabilityResult.retry_after_s。
# ==================================
# 版本: v1.2
# 日期: 2026-06-14
# 修改说明: 为 _send_request 和 _send_streaming_request 的网络请求添加 asyncio.wait_for 强超时包裹（设为总超时秒数 + 2秒缓冲），从根本上避免因为底层 socket 挂死或服务器慢速响应导致整个探测卡死的问题。
# ==================================

"""探针基类，提供通用功能。

BaseProbe 提供：
    - 通用 HTTP 请求方法（非流式 + 流式，均测首字节延迟）
    - 异常分类（_classify_exception）：网络层 / HTTP 层
    - 不可用原因推断（_infer_unavailable_reason）：兼容 Stage2.5 旧逻辑
    - ProbeTimeouts 注入：fast_threshold / slow_threshold 决定 httpx 实际超时
"""
from __future__ import annotations

import asyncio
from typing import Optional

import httpx

from ..constants import (
    DEFAULT_CONNECT_TIMEOUT_S,
    DEFAULT_FAST_THRESHOLD_MS,
    DEFAULT_SLOW_THRESHOLD_MS,
    ErrorCategory,
    ModelAvailability,
    ResponseHealth,
    UnavailableReason,
    TransportMode,
    classify_response_health,
)
from ..error_taxonomy import (
    classify as _taxonomy_classify,
    signal_from_exception as _signal_from_exc,
    signal_from_response as _signal_from_resp,
)
from ..models import CapabilityResult, PlatformConfig, ProbeTimeouts
from ..adapters.base import FormatAdapter
from ..secret import SecretResolver
from ..engine.stages import normalize_base_url


def _reason_from_category(category: str) -> str:
    """将 ErrorCategory 映射到 UnavailableReason。"""
    _MAP = {
        ErrorCategory.CONNECT_FAILED.value:        UnavailableReason.NETWORK_ERROR.value,
        ErrorCategory.READ_TIMEOUT.value:          UnavailableReason.NETWORK_ERROR.value,
        ErrorCategory.OTHER_SIDE_CLOSED.value:     UnavailableReason.NETWORK_ERROR.value,
        ErrorCategory.PROXY_BLOCKED.value:         UnavailableReason.NETWORK_ERROR.value,
        ErrorCategory.HTTP_AUTH.value:            UnavailableReason.AUTH_FAILED.value,
        ErrorCategory.HTTP_FORBIDDEN.value:       UnavailableReason.PERMISSION_DENIED.value,
        ErrorCategory.HTTP_NOT_FOUND.value:       UnavailableReason.MODEL_NOT_FOUND.value,
        ErrorCategory.HTTP_RATE_LIMITED.value:    UnavailableReason.QUOTA_EXCEEDED.value,
        ErrorCategory.HTTP_PAYMENT_REQUIRED.value: UnavailableReason.PAYMENT_REQUIRED.value,
        ErrorCategory.EMPTY_RESPONSE.value:       UnavailableReason.RESPONSE_INVALID.value,
        ErrorCategory.MALFORMED_RESPONSE.value:   UnavailableReason.RESPONSE_INVALID.value,
        ErrorCategory.INCOHERENT_RESPONSE.value:  UnavailableReason.RESPONSE_INCOHERENT.value,
        ErrorCategory.UNKNOWN.value:              UnavailableReason.UNKNOWN.value,
    }
    return _MAP.get(category, UnavailableReason.UNKNOWN.value)


class BaseProbe:
    """探针基类，提供通用 HTTP 请求和错误处理。

    设计理念：
        将重复的 HTTP 请求、延迟测量、错误推断逻辑提取到基类，
        子类只需关注特定能力的测试逻辑。

    超时策略：
        httpx 实际超时 = slow_threshold_ms（默认 60s）。
        子类根据 first_byte_latency_ms 与 fast/slow 阈值比较，
        映射到 ResponseHealth（HEALTHY / SLUGGISH / DEAD）。
    """

    def __init__(
        self,
        timeouts: Optional[ProbeTimeouts] = None,
        timeout: Optional[float] = None,
    ) -> None:
        """初始化探针。

        Args:
            timeouts: 响应分级阈值配置，决定 httpx 总超时与 fast/slow 分级
            timeout: 兼容旧 API，仅当 timeouts 为 None 时生效（视为 slow_threshold）
        """
        if timeouts is None:
            slow_ms = int(timeout * 1000) if timeout else DEFAULT_SLOW_THRESHOLD_MS
            timeouts = ProbeTimeouts(
                fast_threshold_ms=min(DEFAULT_FAST_THRESHOLD_MS, slow_ms),
                slow_threshold_ms=slow_ms,
                connect_timeout_s=DEFAULT_CONNECT_TIMEOUT_S,
            )
        self._timeouts = timeouts
        # 兼容旧字段（部分子类直接读 self._timeout）
        self._timeout = timeouts.total_timeout_s

    # ──────────────────────────────────────────────────────────────────
    # 非流式请求
    # ──────────────────────────────────────────────────────────────────

    async def _send_request(
        self,
        platform: PlatformConfig,
        model: str,
        adapter: FormatAdapter,
        request_body: dict,
        endpoint: str = "/chat/completions",
    ) -> tuple[httpx.Response, float]:
        """发送非流式 HTTP 请求并测量延迟。

        Returns:
            (响应对象, 延迟毫秒数)

        Raises:
            httpx.HTTPError 及子类：网络层错误，由子类用 _classify_exception 归类
        """
        base_url = normalize_base_url(str(platform.base_url))
        api_key = SecretResolver.resolve(platform.api_key)

        headers = adapter.get_headers(api_key)
        endpoint_path = endpoint
        if endpoint == "/chat/completions":
            endpoint_path = adapter.default_endpoint

        if "{model}" in endpoint_path:
            endpoint_path = endpoint_path.format(model=model)

        timeout = httpx.Timeout(
            self._timeouts.total_timeout_s,
            connect=self._timeouts.connect_timeout_s,
        )
        limit_timeout_s = self._timeouts.total_timeout_s + 2.0
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                start = asyncio.get_event_loop().time()
                response = await asyncio.wait_for(
                    client.post(
                        f"{base_url}{endpoint_path}", json=request_body, headers=headers
                    ),
                    timeout=limit_timeout_s,
                )
                latency_ms = (asyncio.get_event_loop().time() - start) * 1000
        except asyncio.TimeoutError:
            raise httpx.ReadTimeout("请求被 asyncio.wait_for 强制超时中断", request=None)

        return response, latency_ms

    # ──────────────────────────────────────────────────────────────────
    # 流式请求（共用实现，供 BasicChat fallback 和 Streaming 探针调用）
    # ──────────────────────────────────────────────────────────────────

    async def _send_streaming_request(
        self,
        platform: PlatformConfig,
        adapter: FormatAdapter,
        request_body: dict,
        endpoint: str = "/chat/completions",
    ) -> dict:
        """发送流式请求，返回首字节延迟 + 完整内容 + 数据块数。

        Args:
            platform: 平台配置
            adapter: 格式适配器（保留参数以备未来按 adapter 解析 SSE）
            request_body: 已带 stream=True 的请求体
            endpoint: API 端点

        Returns:
            {
                "status_code": int,
                "first_byte_latency_ms": float | None,
                "total_latency_ms": float,
                "chunks": list[str],            # 全部 data: 行（含 [DONE]）
                "content": str,                 # 拼接后的纯文本 content
                "has_done": bool,
            }

        Raises:
            httpx 网络异常（交给调用方分类）
        """
        base_url = normalize_base_url(str(platform.base_url))
        api_key = SecretResolver.resolve(platform.api_key)

        model = request_body.get("model", "default")
        headers = adapter.get_headers(api_key)
        headers["Accept"] = "text/event-stream"

        endpoint_path = endpoint
        if endpoint == "/chat/completions":
            endpoint_path = adapter.default_endpoint
            if endpoint_path.endswith(":generateContent"):
                endpoint_path = endpoint_path.replace(":generateContent", ":streamGenerateContent")

        if "{model}" in endpoint_path:
            endpoint_path = endpoint_path.format(model=model)

        chunks: list[str] = []
        first_byte_latency_ms: Optional[float] = None
        start = asyncio.get_event_loop().time()

        timeout = httpx.Timeout(
            self._timeouts.total_timeout_s,
            connect=self._timeouts.connect_timeout_s,
        )
        limit_timeout_s = self._timeouts.total_timeout_s + 2.0

        async def _run_stream() -> dict | None:
            nonlocal first_byte_latency_ms
            async with httpx.AsyncClient(timeout=timeout) as client:
                async with client.stream(
                    "POST",
                    f"{base_url}{endpoint_path}",
                    json=request_body,
                    headers=headers,
                ) as response:
                    status_code = response.status_code
                    if status_code != 200:
                        total_latency_ms = (asyncio.get_event_loop().time() - start) * 1000
                        return {
                            "status_code": status_code,
                            "first_byte_latency_ms": None,
                            "total_latency_ms": total_latency_ms,
                            "chunks": [],
                            "content": "",
                            "has_done": False,
                        }

                    async for line in response.aiter_lines():
                        if not line:
                            continue
                        if first_byte_latency_ms is None:
                            first_byte_latency_ms = (
                                asyncio.get_event_loop().time() - start
                            ) * 1000
                        chunks.append(line)
                        # 支持 OpenAI 和 Anthropic 等流式结束标志
                        if line == "data: [DONE]" or "message_stop" in line or '"done":true' in line:
                            break
            return None

        try:
            res = await asyncio.wait_for(_run_stream(), timeout=limit_timeout_s)
            if res is not None:
                return res
        except asyncio.TimeoutError:
            raise httpx.ReadTimeout("流式读取被 asyncio.wait_for 强制超时中断", request=None)

        total_latency_ms = (asyncio.get_event_loop().time() - start) * 1000

        # 从 SSE chunks 依据适配器格式拼接 content
        content = self._extract_streaming_content(chunks, adapter.name)
        has_done = any(
            c == "data: [DONE]" or "message_stop" in c or '"done":true' in c
            for c in chunks
        )

        return {
            "status_code": 200,
            "first_byte_latency_ms": first_byte_latency_ms,
            "total_latency_ms": total_latency_ms,
            "chunks": chunks,
            "content": content,
            "has_done": has_done,
        }

    @staticmethod
    def _extract_streaming_content(chunks: list[str], adapter_name: str = "openai_chat_completions") -> str:
        """从 SSE data: 行列表中根据不同的适配器格式提取并拼接 content 文本。"""
        import json

        parts: list[str] = []
        for line in chunks:
            payload = line.strip()
            if payload.startswith("data: "):
                payload = payload[len("data: "):].strip()

            if payload == "[DONE]" or not payload:
                continue

            try:
                obj = json.loads(payload)
            except (json.JSONDecodeError, ValueError):
                continue

            # 针对不同协议的流式块解析
            if adapter_name == "openai_chat_completions":
                choices = obj.get("choices") or []
                if choices:
                    delta = choices[0].get("delta") or choices[0].get("message") or {}
                    piece = delta.get("content")
                    if isinstance(piece, str):
                        parts.append(piece)

            elif adapter_name == "openai_text_completions":
                choices = obj.get("choices") or []
                if choices:
                    piece = choices[0].get("text")
                    if isinstance(piece, str):
                        parts.append(piece)

            elif adapter_name == "anthropic_messages":
                # Anthropic: type="content_block_delta" 时，delta.text 含有增量
                if obj.get("type") == "content_block_delta":
                    delta = obj.get("delta") or {}
                    piece = delta.get("text")
                    if isinstance(piece, str):
                        parts.append(piece)

            elif adapter_name == "gemini_native":
                # Gemini: candidates[0].content.parts[0].text
                candidates = obj.get("candidates") or []
                if candidates:
                    content_obj = candidates[0].get("content") or {}
                    parts_list = content_obj.get("parts") or []
                    if parts_list and "text" in parts_list[0]:
                        piece = parts_list[0]["text"]
                        if isinstance(piece, str):
                            parts.append(piece)

            elif adapter_name == "cohere_native":
                # Cohere: type="content-delta", delta.message.content.text
                if obj.get("type") == "content-delta":
                    delta = obj.get("delta") or {}
                    msg = delta.get("message") or {}
                    content_obj = msg.get("content") or {}
                    piece = content_obj.get("text")
                    if isinstance(piece, str):
                        parts.append(piece)

            elif adapter_name == "dashscope_native":
                # DashScope: output.choices[0].message.content
                output = obj.get("output") or {}
                choices = output.get("choices") or []
                if choices:
                    msg = choices[0].get("message") or {}
                    piece = msg.get("content")
                    if isinstance(piece, str):
                        parts.append(piece)

            elif adapter_name == "ollama_native":
                # Ollama: message.content
                msg = obj.get("message") or {}
                piece = msg.get("content") or obj.get("response") # 兼顾 /api/generate
                if isinstance(piece, str):
                    parts.append(piece)

            else:
                # 默认回退到 OpenAI 格式解析
                choices = obj.get("choices") or []
                if choices:
                    delta = choices[0].get("delta") or choices[0].get("message") or {}
                    piece = delta.get("content")
                    if isinstance(piece, str):
                        parts.append(piece)

        return "".join(parts)

    # ──────────────────────────────────────────────────────────────────
    # 异常分类（网络层）—— 委托给 error_taxonomy.classify()
    # ──────────────────────────────────────────────────────────────────

    def _classify_exception(self, exc: Exception) -> tuple[str, str]:
        """将 httpx 异常映射到 ErrorCategory + 人类可读消息。

        Returns:
            (ErrorCategory 枚举 value, 错误消息)
        """
        sig = _signal_from_exc(exc)
        diagnosis = _taxonomy_classify(sig)
        msg = str(exc)

        # 构造与旧行为兼容的人类可读消息
        cat = diagnosis.error_category
        if cat == ErrorCategory.PROXY_BLOCKED.value:
            human_msg = f"代理软件拦截: {msg[:200]}"
        elif cat == ErrorCategory.CONNECT_FAILED.value:
            if isinstance(exc, httpx.ConnectTimeout):
                human_msg = f"TCP 连接超时: {msg[:200]}"
            else:
                human_msg = f"连接失败: {msg[:200]}"
        elif cat == ErrorCategory.READ_TIMEOUT.value:
            if isinstance(exc, httpx.ReadTimeout):
                human_msg = f"读取超时（> {self._timeouts.slow_threshold_ms / 1000:.0f}s 无响应）"
            else:
                human_msg = f"请求超时（> {self._timeouts.slow_threshold_ms / 1000:.0f}s）"
        elif cat == ErrorCategory.OTHER_SIDE_CLOSED.value:
            human_msg = f"上游主动断连: {msg[:200]}"
        else:
            human_msg = msg[:200]

        return cat, human_msg

    # ──────────────────────────────────────────────────────────────────
    # HTTP 错误推断 —— 委托给 error_taxonomy.classify()
    # ──────────────────────────────────────────────────────────────────

    def _infer_unavailable_reason(self, response: httpx.Response) -> UnavailableReason:
        """从响应推断不可用原因。"""
        sig = _signal_from_resp(response)
        diagnosis = _taxonomy_classify(sig)
        return UnavailableReason(diagnosis.unavailable_reason)

    def _infer_error_category_from_status(self, status_code: int) -> str:
        """HTTP 状态码 → ErrorCategory（流式无 body 简化版，直接按状态码分类）。"""
        from ..error_taxonomy import ErrorSignal
        sig = ErrorSignal(status_code=status_code)
        diagnosis = _taxonomy_classify(sig)
        return diagnosis.error_category

    def _http_status_to_unavailable_reason(self, status_code: int) -> str:
        """HTTP 状态码 → UnavailableReason value（流式无 body 时使用）。"""
        from ..error_taxonomy import ErrorSignal
        sig = ErrorSignal(status_code=status_code)
        diagnosis = _taxonomy_classify(sig)
        return diagnosis.unavailable_reason

    # ──────────────────────────────────────────────────────────────────
    # 响应分级（首字节延迟 → ResponseHealth）
    # ──────────────────────────────────────────────────────────────────

    def _classify_health(self, latency_ms: Optional[float]) -> str:
        """latency_ms → ResponseHealth value。"""
        return classify_response_health(
            latency_ms,
            self._timeouts.fast_threshold_ms,
            self._timeouts.slow_threshold_ms,
        )

    # ──────────────────────────────────────────────────────────────────
    # 通用 CapabilityResult 构造器（被所有探针复用）
    # ──────────────────────────────────────────────────────────────────

    def _build_network_error_result(
        self,
        error_category: str,
        error_message: str,
        response_mode: str = "non_streaming",
    ) -> CapabilityResult:
        """网络层异常 → CapabilityResult。"""
        unavailable_reason = _reason_from_category(error_category)
        return CapabilityResult(
            supported=False,
            reliability="unknown",
            availability=ModelAvailability.UNAVAILABLE.value,
            unavailable_reason=unavailable_reason,
            error_category=error_category,
            error_message=error_message,
            detail=error_message,
            response_health=ResponseHealth.DEAD.value,
            response_mode=response_mode,
        )

    def _build_http_error_result(
        self,
        response: httpx.Response,
        latency_ms: float,
        response_mode: str = "non_streaming",
    ) -> CapabilityResult:
        """HTTP 非 200 → CapabilityResult（category + reason 同时产出）。"""
        sig = _signal_from_resp(response)
        diagnosis = _taxonomy_classify(sig)

        try:
            body = response.json()
            error_msg = body.get("error", {}).get("message", response.text[:200])
        except Exception:
            error_msg = response.text[:200]

        retry_after_s: Optional[int] = None
        if response.status_code == 429:
            for header in ("retry-after", "x-ratelimit-reset-requests", "x-ratelimit-reset"):
                val = response.headers.get(header)
                if val:
                    try:
                        val_f = float(val)
                        if val_f > 1700000000:
                            import time
                            diff = int(val_f - time.time())
                            retry_after_s = max(0, diff)
                        else:
                            retry_after_s = int(val_f)
                        break
                    except (ValueError, TypeError):
                        pass

        return CapabilityResult(
            supported=False,
            reliability="unknown",
            availability=ModelAvailability.UNAVAILABLE.value,
            unavailable_reason=diagnosis.unavailable_reason,
            error_code=response.status_code,
            error_category=diagnosis.error_category,
            error_message=error_msg,
            detail=f"HTTP {response.status_code}: {error_msg}",
            latency_ms=latency_ms,
            first_byte_latency_ms=latency_ms,
            response_health=self._classify_health(latency_ms),
            response_mode=response_mode,
            retry_after_s=retry_after_s,
        )

    def _classify_any_exception(self, exc: Exception) -> CapabilityResult:
        """异常 → CapabilityResult 的便捷封装。"""
        category, msg = self._classify_exception(exc)
        return self._build_network_error_result(category, msg)

    async def _send_and_parse(
        self,
        platform: PlatformConfig,
        model: str,
        adapter: FormatAdapter,
        request_body: dict,
        prefer_streaming: bool = False,
        endpoint: str = "/chat/completions",
    ) -> tuple[dict, float, float | None, str]:
        """自适应传输方式发送请求并解析响应。

        根据 prefer_streaming 参数自动选择非流式或流式通道，
        统一返回解析后的 OpenAI 格式 JSON dict。

        Args:
            platform: 平台配置
            model: 模型 ID
            adapter: 格式适配器
            request_body: 请求体（不含 stream 字段，由本方法自动处理）
            prefer_streaming: True=使用流式传输, False=使用非流式传输
            endpoint: API 端点

        Returns:
            (data, latency_ms, first_byte_latency_ms, transport_used)
            - data: 解析后的 JSON dict（OpenAI 格式，含 choices）
            - latency_ms: 总延迟（毫秒）
            - first_byte_latency_ms: 首字节延迟（流式专属，非流式时等于 latency_ms）
            - transport_used: 实际使用的传输方式 "non_streaming" / "streaming"

        Raises:
            _AdaptiveTransportError: 传输层或HTTP层失败（调用方捕获后构造 CapabilityResult）
            Exception: 其他未预期异常
        """
        if not prefer_streaming:
            return await self._send_and_parse_non_streaming(
                platform, model, adapter, request_body, endpoint
            )
        else:
            return await self._send_and_parse_streaming(
                platform, adapter, request_body, endpoint
            )

    async def _send_and_parse_non_streaming(
        self,
        platform: PlatformConfig,
        model: str,
        adapter: FormatAdapter,
        request_body: dict,
        endpoint: str,
    ) -> tuple[dict, float, float | None, str]:
        """非流式路径：发送 → 检查状态码 → 解析 JSON。"""
        response, latency_ms = await self._send_request(
            platform, model, adapter, request_body, endpoint
        )
        if response.status_code != 200:
            raise _AdaptiveTransportError(
                result=self._build_http_error_result(response, latency_ms, "non_streaming")
            )
        try:
            data = response.json()
        except Exception as e:
            raise _AdaptiveTransportError(
                result=CapabilityResult(
                    supported=False,
                    reliability="unknown",
                    unavailable_reason=UnavailableReason.RESPONSE_INVALID.value,
                    error_category=ErrorCategory.MALFORMED_RESPONSE.value,
                    error_message=f"响应解析失败: {e}",
                    detail=f"响应解析失败: {e}",
                    latency_ms=latency_ms,
                    first_byte_latency_ms=latency_ms,
                    response_health=self._classify_health(latency_ms),
                    response_mode="non_streaming",
                    transport_used="non_streaming",
                )
            )
        return data, latency_ms, latency_ms, "non_streaming"

    async def _send_and_parse_streaming(
        self,
        platform: PlatformConfig,
        adapter: FormatAdapter,
        request_body: dict,
        endpoint: str,
    ) -> tuple[dict, float, float | None, str]:
        """流式路径：发送 stream=True → 收集 SSE chunks → 重组为 OpenAI 格式 dict。"""
        stream_body = dict(request_body)
        stream_body["stream"] = True

        stream_result = await self._send_streaming_request(
            platform, adapter, stream_body, endpoint
        )

        status_code = stream_result["status_code"]
        if status_code != 200:
            raise _AdaptiveTransportError(
                result=CapabilityResult(
                    supported=False,
                    reliability="unknown",
                    unavailable_reason=self._http_status_to_unavailable_reason(status_code),
                    error_code=status_code,
                    error_category=self._infer_error_category_from_status(status_code),
                    error_message=f"流式请求 HTTP {status_code}",
                    latency_ms=stream_result["total_latency_ms"],
                    first_byte_latency_ms=stream_result["first_byte_latency_ms"],
                    response_health=self._classify_health(
                        stream_result["first_byte_latency_ms"] or stream_result["total_latency_ms"]
                    ),
                    response_mode="streaming",
                    transport_used="streaming",
                )
            )

        content = stream_result.get("content", "")
        tool_calls = self._extract_streaming_tool_calls(stream_result.get("chunks", []))

        # 重组为 OpenAI 格式 dict
        message: dict = {"role": "assistant"}
        if content:
            message["content"] = content
        if tool_calls:
            message["tool_calls"] = tool_calls

        data = {"choices": [{"message": message}]}

        return (
            data,
            stream_result["total_latency_ms"],
            stream_result["first_byte_latency_ms"],
            "streaming",
        )

    @staticmethod
    def _extract_streaming_tool_calls(chunks: list[str]) -> list[dict]:
        """从 SSE data: 行列表中提取并拼接 tool_calls。

        OpenAI 流式 tool_calls 格式：
            每个 chunk 的 delta.tool_calls[i] 包含:
            - 首次出现: {"index": 0, "id": "call_xxx", "type": "function",
                         "function": {"name": "fn_name", "arguments": ""}}
            - 后续追加: {"index": 0, "function": {"arguments": "部分JSON字符串"}}

        本方法按 index 累积拼接 arguments，最终返回完整的 tool_calls 列表。
        """
        import json as _json

        # {index: {"id": str, "type": str, "function": {"name": str, "arguments": str}}}
        accumulator: dict[int, dict] = {}

        for line in chunks:
            if not line.startswith("data: "):
                continue
            payload = line[len("data: "):].strip()
            if payload == "[DONE]" or not payload:
                continue
            try:
                obj = _json.loads(payload)
            except (ValueError, _json.JSONDecodeError):
                continue

            choices = obj.get("choices") or []
            if not choices:
                continue
            delta = choices[0].get("delta") or {}
            delta_tool_calls = delta.get("tool_calls")
            if not delta_tool_calls:
                continue

            for tc in delta_tool_calls:
                idx = tc.get("index", 0)
                if idx not in accumulator:
                    # 首次出现：初始化
                    accumulator[idx] = {
                        "id": tc.get("id", ""),
                        "type": tc.get("type", "function"),
                        "function": {
                            "name": tc.get("function", {}).get("name", ""),
                            "arguments": tc.get("function", {}).get("arguments", ""),
                        },
                    }
                else:
                    # 后续追加：拼接 arguments
                    fn = tc.get("function", {})
                    if "arguments" in fn:
                        accumulator[idx]["function"]["arguments"] += fn["arguments"]
                    if "name" in fn and fn["name"]:
                        accumulator[idx]["function"]["name"] = fn["name"]
                    if "id" in tc and tc["id"]:
                        accumulator[idx]["id"] = tc["id"]

        if not accumulator:
            return []

        # 按 index 顺序返回
        return [accumulator[i] for i in sorted(accumulator.keys())]


class _AdaptiveTransportError(Exception):
    """_send_and_parse 内部异常：传输层/HTTP层失败时携带预构造的 CapabilityResult。

    调用方捕获后直接返回 self.result，无需重复构造。
    """

    def __init__(self, result: CapabilityResult):
        self.result = result
        super().__init__(str(result.error_message or result.detail))
