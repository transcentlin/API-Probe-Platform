# 修改历史 (Revision History)
# ==================================
# 版本: v1.15
# 日期: 2026-06-17
# 修改说明: 在 Stage 1 格式探针中，支持 platform.hints.format 手动指定与利用 discovery_handler 自动发现真实测试模型，彻底打通非标平台的格式识别与连通逻辑。
# ----------------------------------
# 版本: v1.14
# 日期: 2026-06-16
# 修改说明: 在 Stage 2 端点发现发生异常时，调用 _log_compatibility_alert 将错误写入 reports/compatibility_alerts.json；若发现成功，则调用 _clear_compatibility_alert 移除该平台历史告警。
# ----------------------------------
# 版本: v1.13
# 日期: 2026-06-15
# 修改说明: 在 Stage 2 端点发现中调用 handler.discover 时传入 model_status 字典，使得原生模型的 status 状态能正确回传并运用于 Stage 2.5 预检短路逻辑。
# ----------------------------------
# 版本: v1.12
# 日期: 2026-06-15
# 修改说明: 解耦 Stage 2.5 可用性预检测中硬编码的 /chat/completions 接口路径，改为动态读取并渲染对应适配器的 default_endpoint，同时支持动态生成自定义鉴权 Headers，全面打通 Ollama 等非标协议的预检链路。
# ==================================
# 版本: v1.11
# 日期: 2026-06-15
# 修改说明: 重构 Stage 2 模型发现流程，引入 ModelDiscoveryRegistry 注册表架构。支持通过 PlatformConfig 指定专属发现器（如 openai, cloudflare, ollama），彻底解耦非标端点的拉取细节。
# ==================================
# 版本: v1.10
# 日期: 2026-06-15
# 修改说明: 在 Stage 2 端点发现中，当获取 /models 失败且无 hints 时，不再使用默认的 gpt-3.5-turbo 填补模型列表，而是直接保持为空模型列表，并回退为 0 模型总数，使报告更具统一逻辑。
# ==================================
# 版本: v1.9
# 日期: 2026-06-15
# 修改说明: 在 Stage 2 端点发现中，当获取 /models 接口失败时，记录具体的错误响应或异常信息并传递给 EndpointDiscoveryResult，使报告能够展示为何接口探测失败而回退默认模型。
# ==================================
# 版本: v1.8
# 日期: 2026-06-15
# 修改说明: 优化 Stage1 格式检测中的模型发现逻辑，优先筛选状态健康的活跃模型，避免首个模型 degraded/dead 导致探测打分失效归零。
# ==================================
# 版本: v1.7
# 日期: 2026-06-15
# 修改说明: 重构 Stage1 格式检测，采用 asyncio.gather 并发提交不同适配器的测试 job 并限制 10s 超时；动态适配端点和 Header 以打通 8 种 API 格式的自适应并发嗅探。
# ==================================
# 版本: v1.6
# 日期: 2026-06-15
# 修改说明: 针对 Stage 2.5 可用性预检引入流式 Fallback 兜底（_quick_check / _quick_check_stream_fallback），避免仅支持流式的模型在预检阶段被误杀，全面实现方案 B 宽松通道可用判定。
# ==================================
# 版本: v1.5
# 日期: 2026-06-15
# 修改说明: 实现边界探测的通道自适应与短路优化；在模型仅支持流式时，使用流式 fallback 探测 max_context 与并发压测；若通道不支持或探测超时，在 ModelLimits 中写入具体的 str 原因。
# ==================================
# 版本: v1.4
# 日期: 2026-06-15
# 修改说明: 在 Stage4_LimitsDetection 的 _probe_max_tokens 中，当遇到非 200 或异常时，不直接 break，而是 continue 降档重试下一个值，彻底解决由于大参数报错引发提早中断导致未探测的缺陷。
# ==================================
# 版本: v1.3
# 日期: 2026-06-15
# 修改说明: 在 Stage4_LimitsDetection 中，将 max_tokens 与 context 候选精简为 4 档；重构 _probe_rate_limit_rpm 以解包并记录速率限制的检测来源。
# ==================================
# 版本: v1.2
# 日期: 2026-06-15
# 修改说明: 在 Stage4_LimitsDetection 中重构 _probe_rate_limit_rpm，实现多级自适应探测兜底链路（标准 Header、配额盲扫、被动429反推、并发压测）。
# ==================================
# 版本: v1.1
# 日期: 2026-06-14
# 修改说明: 在 Stage2.5 模型预检测中为 client.post 加装 asyncio.wait_for 强超时包裹，解决某些模型因网络半开或慢速响应导致挂死的问题。

"""Stage 接口与 Stage0 实现（详细设计 §2.4）。

Stage 接口：所有阶段的统一协议
Stage0_Preflight：连通性检查 + website 抓取
"""
from __future__ import annotations

import asyncio
from typing import Protocol

import httpx

from ..constants import (
    StageExecutionError,
    ErrorCategory,
    TransportMode,
    UnavailableReason,
    GATEWAY_PROBES,
)
from ..models import ConnectivityResult, ProbeContext


# ──────────────────────────────────────────────────────────────────────────
# 工具函数
# ──────────────────────────────────────────────────────────────────────────


def normalize_base_url(base_url: str) -> str:
    """规范化 base_url：移除末尾斜杠，避免拼接时出现双斜杠。

    Args:
        base_url: 原始 base_url

    Returns:
        规范化后的 base_url（无末尾斜杠）

    Examples:
        >>> normalize_base_url("https://api.example.com/")
        'https://api.example.com'
        >>> normalize_base_url("https://api.example.com")
        'https://api.example.com'
    """
    return base_url.rstrip("/")


# ──────────────────────────────────────────────────────────────────────────
# Stage 接口（详细设计 §2.4）
# ──────────────────────────────────────────────────────────────────────────


class Stage(Protocol):
    """阶段执行协议（所有 Stage 必须实现）。"""

    @property
    def stage_number(self) -> int:
        """阶段编号 0~5。"""
        ...

    @property
    def stage_name(self) -> str:
        """阶段名称（用于日志）。"""
        ...

    async def run(self, ctx: ProbeContext) -> None:
        """执行阶段，产出写入 ctx。

        Args:
            ctx: 探测上下文

        Raises:
            StageExecutionError: 阶段执行失败
        """
        ...


# ──────────────────────────────────────────────────────────────────────────
# Stage0：预检查（详细设计 §2.4 Stage0_Preflight）
# ──────────────────────────────────────────────────────────────────────────


class Stage0_Preflight:
    """Stage0：连通性检查 + website 抓取（对应 FR-PROBE-02）。

    产出写入 ctx.connectivity：
        - reachable: 是否可达
        - status_code: HTTP 状态码
        - latency_ms: 延迟
        - website_title: 官网标题（若提供 website）
    """

    @property
    def stage_number(self) -> int:
        return 0

    @property
    def stage_name(self) -> str:
        return "预检查"

    async def run(self, ctx: ProbeContext) -> None:
        """执行 Stage0。"""
        platform = ctx.platform
        base_url = normalize_base_url(str(platform.base_url))

        # 创建 HTTP 客户端（详细设计 §6.2 重试策略）
        # 注意：不要显式传 transport=，否则会绕过 HTTPS_PROXY 环境变量。
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(30.0, connect=10.0),
        ) as client:
            # 1. 连通性检查：HEAD 请求 base_url
            try:
                start = asyncio.get_event_loop().time()
                response = await asyncio.wait_for(
                    client.head(base_url, follow_redirects=True),
                    timeout=32.0
                )
                latency_ms = (asyncio.get_event_loop().time() - start) * 1000

                ctx.connectivity = ConnectivityResult(
                    reachable=True,
                    status_code=response.status_code,
                    latency_ms=latency_ms,
                )
            except (httpx.TimeoutException, httpx.ConnectError, asyncio.TimeoutError) as e:
                ctx.connectivity = ConnectivityResult(
                    reachable=False,
                    error=f"连接失败: {type(e).__name__}",
                )
                raise StageExecutionError(f"Stage0 连通性检查失败: {e}")

            # 2. website 抓取（可选）
            if platform.website:
                try:
                    website_response = await asyncio.wait_for(
                        client.get(str(platform.website), follow_redirects=True),
                        timeout=15.0
                    )
                    if website_response.status_code == 200:
                        # 简单提取 <title>
                        html = website_response.text
                        title_start = html.find("<title>")
                        title_end = html.find("</title>")
                        if title_start != -1 and title_end != -1:
                            title = html[title_start + 7 : title_end].strip()
                            ctx.connectivity.website_title = title
                except Exception:
                    # website 抓取失败不影响主流程
                    pass


# ──────────────────────────────────────────────────────────────────────────
# Stage1：格式识别（详细设计 §2.4 Stage1_FormatDetection）
# ──────────────────────────────────────────────────────────────────────────


class Stage1_FormatDetection:
    """Stage1：遍历适配器打分识别格式（对应 FR-PROBE-03）。

    产出写入 ctx.format_detection：
        - detected_format: 识别出的格式
        - confidence: 置信度
        - scores: 各适配器打分详情
    """

    def __init__(self, adapter_registry):
        """初始化 Stage1。

        Args:
            adapter_registry: AdapterRegistry 实例
        """
        self._adapter_registry = adapter_registry

    @property
    def stage_number(self) -> int:
        return 1

    @property
    def stage_name(self) -> str:
        return "格式识别"

    async def run(self, ctx: ProbeContext) -> None:
        """执行 Stage1：并发测试各适配器打分并识别格式。"""
        from ..models import FormatDetectionResult
        from ..secret import SecretResolver

        platform = ctx.platform
        # 1. 优先支持 hints.format 手动指定并短路
        if platform.hints and platform.hints.format:
            from ..constants import KNOWN_FORMATS, FORMAT_OPENAI, FORMAT_OLLAMA, FORMAT_ANTHROPIC, FORMAT_GEMINI, FORMAT_COHERE, FORMAT_DASHSCOPE
            fmt_hint = platform.hints.format
            mapping = {
                "openai": FORMAT_OPENAI,
                "openai-chat": FORMAT_OPENAI,
                "openai_chat_completions": FORMAT_OPENAI,
                "ollama": FORMAT_OLLAMA,
                "ollama-native": FORMAT_OLLAMA,
                "ollama_native": FORMAT_OLLAMA,
                "anthropic": FORMAT_ANTHROPIC,
                "anthropic-messages": FORMAT_ANTHROPIC,
                "anthropic_messages": FORMAT_ANTHROPIC,
                "gemini": FORMAT_GEMINI,
                "gemini-native": FORMAT_GEMINI,
                "gemini_native": FORMAT_GEMINI,
                "cohere": FORMAT_COHERE,
                "cohere-native": FORMAT_COHERE,
                "cohere_native": FORMAT_COHERE,
                "dashscope": FORMAT_DASHSCOPE,
                "dashscope-native": FORMAT_DASHSCOPE,
                "dashscope_native": FORMAT_DASHSCOPE
            }
            mapped_fmt = mapping.get(fmt_hint.lower(), fmt_hint)
            if mapped_fmt in KNOWN_FORMATS:
                ctx.format_detection = FormatDetectionResult(
                    detected_format=mapped_fmt,
                    confidence=1.0,
                    scores={mapped_fmt: 1.0}
                )
                return

        base_url = normalize_base_url(str(platform.base_url))

        # 解析密钥
        api_key = SecretResolver.resolve(platform.api_key)
        
        # 默认 Header 用于探测模型 ID
        default_headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

        test_prompt = "Hello"

        scores = {}
        if not hasattr(ctx, '_stage1_errors'):
            ctx._stage1_errors = {}

        async with httpx.AsyncClient(timeout=30.0) as client:
            # 先探测一个真实模型 ID，提高探针有效性（探索式发现，避免硬编码模型不存在导致打分失真）
            test_model = await self._discover_test_model(client, base_url, default_headers, platform)

            async def _probe_single(adapter) -> None:
                try:
                    # 动态自适应端点并处理模型占位符
                    endpoint_path = adapter.default_endpoint
                    if "{model}" in endpoint_path:
                        endpoint_path = endpoint_path.format(model=test_model)

                    endpoint = f"{base_url}{endpoint_path}"
                    custom_headers = adapter.get_headers(api_key)
                    request_body = adapter.build_probe_request(test_prompt, test_model)

                    # 发送请求，限定 10.0 秒超时，并使用 wait_for 12.0s 强超时双重防护以保证并发性能
                    response = await asyncio.wait_for(
                        client.post(
                            endpoint, json=request_body, headers=custom_headers, timeout=10.0
                        ),
                        timeout=12.0
                    )
                    score = adapter.score(response)
                    scores[adapter.name] = score
                except Exception as e:
                    scores[adapter.name] = 0.0
                    ctx._stage1_errors[adapter.name] = str(e)

            # 并发执行嗅探任务
            tasks = [
                _probe_single(adapter)
                for adapter in self._adapter_registry.get_all()
            ]
            await asyncio.gather(*tasks)

        # 选择最高分
        if not scores:
            raise StageExecutionError("Stage1 所有适配器打分失败")

        best_format = max(scores, key=scores.get)
        best_score = scores[best_format]

        # 若最高分也是 0.00，代表没有识别出任何已知格式，优先 fallback 回退到最通用的 openai_chat_completions
        if best_score <= 0.0:
            from ..constants import FORMAT_OPENAI
            if FORMAT_OPENAI in scores:
                best_format = FORMAT_OPENAI
                best_score = 0.0

        ctx.format_detection = FormatDetectionResult(
            detected_format=best_format,
            confidence=best_score,
            scores=scores,
        )

    @staticmethod
    async def _discover_test_model(
        client: httpx.AsyncClient, base_url: str, headers: dict, platform
    ) -> str:
        """探测一个可用模型 ID 用于格式探针。

        优先级：用户 hint > /models 端点首个模型（优先选择健康模型） > 默认值。
        这样 Stage1 的探针请求才能命中真实模型，避免因模型不存在或不可用导致打分恒为 0。
        """
        # 1. 用户提示优先
        if platform.hints and platform.hints.models:
            return platform.hints.models[0]

        # 1.5 尝试使用平台指定的 discovery_handler 来获取真实模型
        if platform.discovery_handler:
            try:
                from ..discovery import discovery_registry
                from ..secret import SecretResolver
                handler = discovery_registry.get(platform.discovery_handler)
                api_key = SecretResolver.resolve(platform.api_key)
                m_status = {}
                models = await handler.discover(client, base_url, api_key, platform, model_status=m_status)
                if models:
                    healthy_models = [
                        m for m in models
                        if m_status.get(m, "").lower() not in ["dead", "offline", "degraded"]
                    ]
                    if healthy_models:
                        return healthy_models[0]
                    return models[0]
            except Exception:
                pass

        # 2. 尝试 /models 端点
        try:
            resp = await client.get(f"{base_url}/models", headers=headers)
            if resp.status_code == 200:
                data = resp.json()
                if isinstance(data, dict) and data.get("data"):
                    models_list = data["data"]
                    # 优先挑选健康状态（非 dead/offline/degraded）的模型
                    healthy_models = []
                    for m in models_list:
                        if isinstance(m, dict) and "id" in m:
                            m_status = str(m.get("status", "")).lower()
                            if m_status not in ["dead", "offline", "degraded"]:
                                healthy_models.append(m["id"])
                    
                    if healthy_models:
                        return healthy_models[0]
                    # 如果没有健康模型，退而求其次找第一个有 ID 的模型
                    for m in models_list:
                        if isinstance(m, dict) and "id" in m:
                            return m["id"]
        except Exception:
            pass

        # 3. 默认回退
        return "gpt-3.5-turbo"


def _log_compatibility_alert(platform_name: str, base_url: str, handler_name: str, error_message: str):
    """记录平台模型发现处理器的兼容性异常告警。"""
    import json
    from pathlib import Path
    from datetime import datetime

    try:
        reports_dir = Path(__file__).resolve().parent.parent.parent.parent / "reports"
        reports_dir.mkdir(parents=True, exist_ok=True)
        alerts_file = reports_dir / "compatibility_alerts.json"
        
        alerts = []
        if alerts_file.exists():
            try:
                with open(alerts_file, "r", encoding="utf-8") as f:
                    alerts = json.load(f)
            except Exception:
                alerts = []
        
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        new_alert = {
            "platform_name": platform_name,
            "base_url": base_url,
            "handler_name": handler_name,
            "error_message": error_message,
            "detected_at": now_str,
            "suggestion": f"默认的 '{handler_name}' 发现处理器请求失败或检测到非标准返回格式。若此平台使用特殊 API 端点结构，建议为此平台开发并注册新的 ModelDiscoveryHandler。"
        }
        
        # 移除旧的平台记录并置顶
        alerts = [a for a in alerts if a.get("platform_name") != platform_name]
        alerts.insert(0, new_alert)
        alerts = alerts[:50]
        
        with open(alerts_file, "w", encoding="utf-8") as f:
            json.dump(alerts, f, ensure_ascii=False, indent=2)
            
    except Exception as e:
        print(f"[Warning] 写入兼容性告警文件失败: {e}")


def _clear_compatibility_alert(platform_name: str):
    """清除指定平台的兼容性异常告警。"""
    import json
    from pathlib import Path

    try:
        reports_dir = Path(__file__).resolve().parent.parent.parent.parent / "reports"
        alerts_file = reports_dir / "compatibility_alerts.json"
        
        if alerts_file.exists():
            try:
                with open(alerts_file, "r", encoding="utf-8") as f:
                    alerts = json.load(f)
            except Exception:
                return
            
            original_len = len(alerts)
            alerts = [a for a in alerts if a.get("platform_name") != platform_name]
            
            if len(alerts) < original_len:
                with open(alerts_file, "w", encoding="utf-8") as f:
                    json.dump(alerts, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"[Warning] 清除兼容性告警文件失败: {e}")


# ──────────────────────────────────────────────────────────────────────────
# Stage2：端点发现（详细设计 §2.4 Stage2_EndpointDiscovery）
# ──────────────────────────────────────────────────────────────────────────


class Stage2_EndpointDiscovery:
    """Stage2：发现端点 + 获取模型列表（对应 FR-PROBE-04）。

    产出写入 ctx.endpoint_discovery：
        - endpoints: 端点映射 {"chat": "/v1/chat/completions", "models": "/v1/models"}
        - models: 模型 ID 列表
        - discovery_method: 发现方式（api/hint/fallback）
    """

    @property
    def stage_number(self) -> int:
        return 2

    @property
    def stage_name(self) -> str:
        return "端点发现"

    async def run(self, ctx: ProbeContext) -> None:
        """执行 Stage2：尝试 /v1/models 端点获取模型列表。"""
        from ..models import EndpointDiscoveryResult
        from ..secret import SecretResolver

        platform = ctx.platform
        base_url = normalize_base_url(str(platform.base_url))
        api_key = SecretResolver.resolve(platform.api_key)

        # 默认端点（OpenAI 兼容）
        endpoints = {
            "chat": f"{base_url}/chat/completions",
            "models": f"{base_url}/models",
        }

        models = []
        model_status: dict[str, str] = {}  # M2++：保留平台原生 status 字段
        discovery_method = "fallback"
        error_message = None

        # 根据配置路由调用专属的模型发现处理器
        handler_name = platform.discovery_handler or "openai"
        async with httpx.AsyncClient(timeout=30.0) as client:
            try:
                from ..discovery import discovery_registry
                handler = discovery_registry.get(handler_name)
                models = await handler.discover(
                    client, base_url, api_key, platform, model_status=model_status
                )
                if models:
                    discovery_method = "api"
                # 成功获取到了模型，清除已存在的异常告警
                _clear_compatibility_alert(platform.name)
            except Exception as e:
                if isinstance(e, httpx.HTTPStatusError):
                    error_message = f"HTTP {e.response.status_code}: {e.response.text[:200]}"
                else:
                    error_message = f"[{handler_name}] 发现失败: {type(e).__name__}({e})"
                # 出现发现异常，记录告警
                _log_compatibility_alert(platform.name, base_url, handler_name, error_message)

        # 回退：使用 hints 或默认模型
        if not models:
            if platform.hints and platform.hints.models:
                models = platform.hints.models
                discovery_method = "hint"
            else:
                models = []  # 不使用 "gpt-3.5-turbo" 兜底
                discovery_method = "fallback"

        ctx.endpoint_discovery = EndpointDiscoveryResult(
            endpoints=endpoints,
            models=models,
            discovery_method=discovery_method,
            model_status=model_status,
            error_message=error_message,
        )


# ──────────────────────────────────────────────────────────────────────────
# Stage2.5：模型可用性预检（M2 核心创新）
# ──────────────────────────────────────────────────────────────────────────


class Stage2_5_ModelAvailabilityCheck:
    """Stage2.5：模型可用性预检（M2 核心创新）。

    设计理念：
        在 Stage2 发现模型列表后，Stage3 能力探测前，快速筛选不可用模型。
        避免对无权限模型执行 8 次探针请求（节省时间和配额）。

    实测效果（Nvidia 案例）：
        - Stage2 发现 118 个模型
        - Stage2.5 预检发现仅 10 个可用
        - Stage3 从 118×8=944 次请求 → 10×8=80 次请求（节省 92%）

    策略：
        对每个模型发送最简单的 chat 请求（max_tokens=1），
        根据 HTTP 状态码和响应体判断可用性。

    产出写入 ctx.model_availability_check：
        - available_models: 可用模型列表
        - unavailable_models: 不可用模型字典（含原因）
        - check_duration_ms: 预检总耗时
    """

    def __init__(self, adapter_registry):
        """初始化 Stage2.5。

        Args:
            adapter_registry: AdapterRegistry 实例（复用 Stage1 的适配器）
        """
        self._adapter_registry = adapter_registry

    @property
    def stage_number(self) -> int:
        # 逻辑上是 2.5，但为了兼容现有 Stage 协议，编号为 2
        # ProbeEngine 通过 stage_name 区分
        return 2

    @property
    def stage_name(self) -> str:
        return "模型可用性预检"

    async def run(self, ctx: ProbeContext) -> None:
        """执行 Stage2.5。

        Args:
            ctx: 探测上下文（需要 Stage1 的 format_detection 和 Stage2 的 endpoint_discovery）

        Raises:
            StageExecutionError: 预检失败
        """
        import time
        from typing import Optional

        from ..constants import UnavailableReason
        from ..models import ModelAvailabilityCheckResult
        from ..secret import SecretResolver

        # 前置检查
        if not ctx.format_detection:
            raise StageExecutionError("Stage2.5 依赖 Stage1 格式识别结果")
        if not ctx.endpoint_discovery:
            raise StageExecutionError("Stage2.5 依赖 Stage2 端点发现结果")

        platform = ctx.platform
        base_url = normalize_base_url(str(platform.base_url))
        api_key = SecretResolver.resolve(platform.api_key)

        # 获取适配器
        adapter = self._adapter_registry.get(ctx.format_detection.detected_format)
        if not adapter:
            raise StageExecutionError(
                f"未找到格式适配器: {ctx.format_detection.detected_format}"
            )

        models = ctx.endpoint_discovery.models
        if not models:
            # 无模型可测，直接返回空结果
            ctx.model_availability_check = ModelAvailabilityCheckResult(
                available_models=[],
                unavailable_models={},
                check_duration_ms=0.0,
            )
            return

        # 执行预检
        start_time = time.time()
        available_models = []
        unavailable_models = {}
        degraded_models: dict[str, str] = {}  # 平台标 degraded 但实测通过的模型

        # M2++ 短路：平台原生 status=dead 的模型直接判不可用，不发请求
        native_status = ctx.endpoint_discovery.model_status or {}
        models_to_probe: list[str] = []
        for model in models:
            raw = native_status.get(model, "").lower()
            if raw in ("dead", "down", "offline", "disabled", "unavailable"):
                unavailable_models[model] = {
                    "reason": UnavailableReason.PLATFORM_DEAD.value,
                    "error": f"平台 /models 接口原生标记 status={raw}",
                    "native_status": raw,
                }
            else:
                # healthy / degraded / unknown 都进入实测探测
                models_to_probe.append(model)

        # 注意：不要显式传 transport=，否则会绕过 HTTPS_PROXY 环境变量，
        # 导致裸 IP 直连被某些 API 网关（如 Cloudflare WAF）拒绝 403 Forbidden。
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(15.0, connect=5.0),
        ) as client:
            # 并发控制：最多 10 个并发请求
            semaphore = asyncio.Semaphore(10)

            tasks = [
                self._check_model_with_semaphore(
                    semaphore, client, base_url, api_key, model, adapter
                )
                for model in models_to_probe
            ]

            results = await asyncio.gather(*tasks, return_exceptions=True)

            for model, result in zip(models_to_probe, results):
                native = native_status.get(model, "").lower()
                if isinstance(result, Exception):
                    # 异常视为不可用
                    unavailable_models[model] = {
                        "reason": UnavailableReason.UNKNOWN.value,
                        "error": str(result),
                        "native_status": native or None,
                    }
                elif result.get("available"):
                    # M2++：实测可用，但平台标 degraded 时记入旁路标记（仍计为可用）
                    if native == "degraded":
                        degraded_models[model] = native
                    available_models.append(model)
                else:
                    if native:
                        result = dict(result)
                        result["native_status"] = native
                    unavailable_models[model] = result

        duration_ms = (time.time() - start_time) * 1000

        # 写入上下文
        ctx.model_availability_check = ModelAvailabilityCheckResult(
            available_models=available_models,
            unavailable_models=unavailable_models,
            check_duration_ms=duration_ms,
            degraded_models=degraded_models,
        )

    async def _check_model_with_semaphore(
        self,
        semaphore: asyncio.Semaphore,
        client: httpx.AsyncClient,
        base_url: str,
        api_key: str,
        model: str,
        adapter,
    ) -> dict:
        """带信号量的模型检查（并发控制）。"""
        async with semaphore:
            return await self._quick_check(client, base_url, api_key, model, adapter)

    async def _quick_check(
        self,
        client: httpx.AsyncClient,
        base_url: str,
        api_key: str,
        model: str,
        adapter,
    ) -> dict:
        """快速检查单个模型可用性。

        Args:
            client: httpx 客户端
            base_url: API 基础 URL
            api_key: API 密钥
            model: 模型 ID
            adapter: 格式适配器

        Returns:
            检查结果字典：
                - available: bool
                - reason: str (不可用时)
                - status_code: int (不可用时)
                - error: str (不可用时)
        """
        headers = adapter.get_headers(api_key)

        # 构造最简单的请求（1 token）
        request_body = adapter.build_probe_request("Hi", model, max_tokens=1)

        endpoint_path = adapter.default_endpoint
        if "{model}" in endpoint_path:
            endpoint_path = endpoint_path.format(model=model)

        non_stream_error = None
        non_stream_status_code = None
        non_stream_reason = None

        try:
            # 使用 asyncio.wait_for 提供强力外部超时控制，避免底层 socket 挂死
            response = await asyncio.wait_for(
                client.post(
                    f"{base_url}{endpoint_path}",
                    json=request_body,
                    headers=headers,
                    timeout=10.0,
                ),
                timeout=12.0,
            )

            if response.status_code == 200:
                # 成功响应，模型可用
                return {"available": True}
            else:
                # HTTP 错误，记录并 fallback
                non_stream_status_code = response.status_code
                non_stream_reason = self._infer_unavailable_reason(response).value
                non_stream_error = response.text[:200]

        except (httpx.TimeoutException, TimeoutError):
            from ..constants import UnavailableReason
            non_stream_reason = UnavailableReason.UNKNOWN.value
            non_stream_error = "非流式请求超时"
        except httpx.ConnectError as e:
            from ..constants import UnavailableReason
            non_stream_reason = UnavailableReason.UNKNOWN.value
            non_stream_error = f"非流式连接失败: {e}"
        except Exception as e:
            from ..constants import UnavailableReason
            non_stream_reason = UnavailableReason.UNKNOWN.value
            non_stream_error = f"非流式异常: {str(e)}"

        # 非流式失败，进行流式预检兜底
        return await self._quick_check_stream_fallback(
            client, base_url, headers, request_body, non_stream_reason, non_stream_status_code, non_stream_error, endpoint_path
        )

    async def _quick_check_stream_fallback(
        self,
        client: httpx.AsyncClient,
        base_url: str,
        headers: dict,
        request_body: dict,
        non_stream_reason: Optional[str],
        non_stream_status_code: Optional[int],
        non_stream_error: Optional[str],
        endpoint_path: str = "/chat/completions",
    ) -> dict:
        """流式预检兜底。"""
        import copy
        stream_body = copy.deepcopy(request_body)
        stream_body["stream"] = True

        try:
            # 流式获取首字节/状态码
            async with client.stream(
                "POST",
                f"{base_url}{endpoint_path}",
                json=stream_body,
                headers=headers,
                timeout=10.0,
            ) as response:
                if response.status_code == 200:
                    # 流式成功，模型可用
                    return {"available": True}
                else:
                    await response.aread()
                    reason = self._infer_unavailable_reason(response)
                    return {
                        "available": False,
                        "reason": reason.value,
                        "status_code": response.status_code,
                        "error": f"流式失败 (HTTP {response.status_code})。非流式原因: {non_stream_error}",
                    }
        except Exception as e:
            from ..constants import UnavailableReason
            # 均失败，判定为不可用模型
            final_reason = non_stream_reason or UnavailableReason.UNKNOWN.value
            final_error = f"流式异常: {str(e)}。非流式原因: {non_stream_error}"
            return {
                "available": False,
                "reason": final_reason,
                "status_code": non_stream_status_code,
                "error": final_error,
            }

    def _infer_unavailable_reason(self, response: httpx.Response):
        """从 HTTP 响应推断不可用原因，委托给 error_taxonomy.classify()。"""
        from ..constants import UnavailableReason
        from ..error_taxonomy import classify as _classify, signal_from_response

        platform_name = None  # Stage2.5 暂无平台名上下文（_quick_check 中不传 platform_name）
        sig = signal_from_response(response, platform_name=platform_name)
        diagnosis = _classify(sig)
        return UnavailableReason(diagnosis.unavailable_reason)


# ──────────────────────────────────────────────────────────────────────────
# Stage3：能力探测（M2 核心）
# ──────────────────────────────────────────────────────────────────────────


class Stage3_CapabilityProbing:
    """Stage3：能力探测调度（M2 核心）。

    设计理念：
        对「可用模型 × 探针」笛卡尔积调度，测试每个模型的 8 项能力。
        只测试 Stage2.5 筛选出的可用模型（节省配额）。

    策略：
        - 并发控制：使用 asyncio.Semaphore(5) 限制并发数
        - 容错处理：单个探针失败不影响其他探针
        - 结果写入：ctx.capabilities[f"{model}:{probe.name}"] = result

    产出写入 ctx.capabilities：
        - 键格式："{model_id}:{probe_name}"
        - 值类型：CapabilityResult
    """

    def __init__(self, probes: list, adapter_registry):
        """初始化 Stage3。

        Args:
            probes: 探针实例列表（实现 CapabilityProbe 协议）
            adapter_registry: AdapterRegistry 实例
        """
        self._probes = probes
        self._adapter_registry = adapter_registry

    @property
    def stage_number(self) -> int:
        return 3

    @property
    def stage_name(self) -> str:
        return "能力探测"

    async def run(self, ctx: ProbeContext) -> None:
        """执行 Stage3（两阶段自适应调度）。"""
        # 前置检查
        if not ctx.format_detection:
            raise StageExecutionError("Stage3 依赖 Stage1 格式识别结果")
        if not ctx.endpoint_discovery:
            raise StageExecutionError("Stage3 依赖 Stage2 端点发现结果")

        # 获取适配器
        adapter = self._adapter_registry.get(ctx.format_detection.detected_format)
        if not adapter:
            raise StageExecutionError(
                f"未找到格式适配器: {ctx.format_detection.detected_format}"
            )

        # 获取要测试的模型列表
        models = self._get_models_to_test(ctx)
        if not models:
            return

        semaphore = asyncio.Semaphore(10)  # 并发控制

        # ── Phase 1: Gateway ──────────────────────────────────────
        # 分离 Gateway 探针（streaming + basic_chat）和扩展探针
        gateway_probes = [p for p in self._probes if p.name in GATEWAY_PROBES]
        extended_probes = [p for p in self._probes if p.name not in GATEWAY_PROBES]

        # 并发执行所有模型的 Gateway 探针
        gateway_tasks = []
        for model in models:
            for probe in gateway_probes:
                gateway_tasks.append(
                    self._probe_with_semaphore(
                        semaphore, probe, ctx.platform, model, adapter, ctx
                    )
                )
        await asyncio.gather(*gateway_tasks, return_exceptions=True)

        # 判定每个模型的传输模式
        transport_modes: dict[str, str] = {}
        for model in models:
            transport_modes[model] = self._determine_transport_mode(model, ctx)
        ctx.transport_modes = transport_modes

        # ── Phase 2: Extended（自适应能力探测）────────────────────
        extended_tasks = []
        for model in models:
            mode = transport_modes[model]

            if mode == TransportMode.DEAD.value:
                # 熔断：直接填充 6 项 supported=False
                self._circuit_break_model(model, extended_probes, ctx)
                continue

            prefer_streaming = (mode == TransportMode.STREAMING_ONLY.value)
            for probe in extended_probes:
                extended_tasks.append(
                    self._probe_with_semaphore_adaptive(
                        semaphore,
                        probe,
                        ctx.platform,
                        model,
                        adapter,
                        ctx,
                        prefer_streaming=prefer_streaming,
                    )
                )

        if extended_tasks:
            await asyncio.gather(*extended_tasks, return_exceptions=True)

    def _determine_transport_mode(self, model: str, ctx: ProbeContext) -> str:
        """根据 Gateway 探针结果判定模型的传输模式。"""
        bc_result = ctx.capabilities.get(f"{model}:basic_chat")
        st_result = ctx.capabilities.get(f"{model}:streaming")

        st_ok = bool(st_result and st_result.supported)

        # 判定非流式通道是否正常
        bc_transport_ok = False
        if bc_result:
            if bc_result.supported:
                # basic_chat 通过 — 检查是走了非流式还是流式 fallback
                if bc_result.response_mode == "non_streaming":
                    bc_transport_ok = True
                # "streaming_fallback" 说明非流式失败，走了流式兜底，因此 bc_transport_ok 保持 False
            else:
                # basic_chat 失败 — 区分传输层故障 vs 内容层故障
                if (
                    bc_result.response_mode == "non_streaming"
                    and bc_result.error_category == ErrorCategory.INCOHERENT_RESPONSE.value
                ):
                    # 非流式拿到了有效 JSON，只是内容被 coherence 判定为语义不连贯 → 传输层是正常的
                    bc_transport_ok = True

        if bc_transport_ok and st_ok:
            return TransportMode.DUAL.value
        elif bc_transport_ok and not st_ok:
            return TransportMode.NON_STREAMING_ONLY.value
        elif not bc_transport_ok and st_ok:
            return TransportMode.STREAMING_ONLY.value
        else:
            return TransportMode.DEAD.value

    def _circuit_break_model(
        self, model: str, extended_probes: list, ctx: ProbeContext
    ) -> None:
        """熔断：为双通道不可用的模型批量填充扩展探针结果。"""
        from ..models import CapabilityResult

        # 继承 Gateway 阶段的错误信息
        bc_result = ctx.capabilities.get(f"{model}:basic_chat")
        inherited_category = (
            bc_result.error_category if bc_result else ErrorCategory.UNKNOWN.value
        )
        inherited_reason = (
            bc_result.unavailable_reason if bc_result else UnavailableReason.UNKNOWN.value
        )
        inherited_msg = bc_result.error_message if bc_result else "双通道不可用"

        for probe in extended_probes:
            key = f"{model}:{probe.name}"
            ctx.capabilities[key] = CapabilityResult(
                supported=False,
                reliability="unknown",
                detail=f"因基础对话与流式探测均失败，自动熔断跳过（{inherited_msg}）",
                error_category=inherited_category,
                unavailable_reason=inherited_reason,
                error_message=f"熔断跳过: {inherited_msg}",
                transport_used="circuit_breaker",
            )

    async def _probe_with_semaphore_adaptive(
        self,
        semaphore: asyncio.Semaphore,
        probe,
        platform,
        model: str,
        adapter,
        ctx: ProbeContext,
        *,
        prefer_streaming: bool = False,
    ) -> None:
        """带信号量 + 自适应传输的探针执行。"""
        async with semaphore:
            try:
                result = await probe.probe(
                    platform, model, adapter, prefer_streaming=prefer_streaming
                )
                key = f"{model}:{probe.name}"
                ctx.capabilities[key] = result
            except Exception as e:
                from ..models import CapabilityResult

                key = f"{model}:{probe.name}"
                ctx.capabilities[key] = CapabilityResult(
                    supported=False,
                    reliability="unknown",
                    detail=f"探针执行失败: {e}",
                    transport_used="streaming" if prefer_streaming else "non_streaming",
                )

    def _get_models_to_test(self, ctx: ProbeContext) -> list[str]:
        """获取要测试的模型列表。

        优先级：
            1. Stage2.5 筛选出的可用模型（节省配额）
            2. Stage2 发现的所有模型（回退）

        Args:
            ctx: 探测上下文

        Returns:
            模型 ID 列表
        """
        # 优先使用 Stage2.5 的可用模型
        if ctx.model_availability_check:
            return ctx.model_availability_check.available_models

        # 回退：使用 Stage2 的所有模型
        if ctx.endpoint_discovery:
            return ctx.endpoint_discovery.models

        return []

    async def _probe_with_semaphore(
        self,
        semaphore: asyncio.Semaphore,
        probe,
        platform,
        model: str,
        adapter,
        ctx: ProbeContext,
    ) -> None:
        """带信号量的探针执行（并发控制）。

        Args:
            semaphore: 信号量
            probe: 探针实例
            platform: 平台配置
            model: 模型 ID
            adapter: 格式适配器
            ctx: 探测上下文
        """
        async with semaphore:
            try:
                result = await probe.probe(platform, model, adapter)
                # 写入结果
                key = f"{model}:{probe.name}"
                ctx.capabilities[key] = result
            except Exception as e:
                # 探针失败：记录错误但不中断流程
                from ..models import CapabilityResult

                key = f"{model}:{probe.name}"
                ctx.capabilities[key] = CapabilityResult(
                    supported=False,
                    reliability="unknown",
                    detail=f"探针执行失败: {e}",
                )


# ──────────────────────────────────────────────────────────────────────────
# 共用工具：按推荐排名取 top-N 可用模型
# ──────────────────────────────────────────────────────────────────────────


def _rank_top_models(ctx: ProbeContext, top_n: int) -> list[str]:
    """返回推荐排名前 top_n 的可用模型 ID 列表。

    排序规则（与 reporter._recommend_models 一致）：
        主键：支持能力数（降序）
        次键：高可靠探针数（降序）
        末键：基础对话延迟（升序）

    若 Stage3 能力数据不足，回退到 Stage2.5 / Stage2 可用模型列表的前 top_n 个。
    """
    if not ctx.capabilities:
        # 无 Stage3 数据，回退
        if ctx.model_availability_check and ctx.model_availability_check.available_models:
            return ctx.model_availability_check.available_models[:top_n]
        if ctx.endpoint_discovery and ctx.endpoint_discovery.models:
            return ctx.endpoint_discovery.models[:top_n]
        return []

    available: set[str] = set()
    if ctx.model_availability_check:
        available = set(ctx.model_availability_check.available_models)

    # 重整为 {model: {probe_name: result}}
    matrix: dict[str, dict] = {}
    for key, result in ctx.capabilities.items():
        if ":" not in key:
            continue
        model_id, probe_name = key.split(":", 1)
        if available and model_id not in available:
            continue
        matrix.setdefault(model_id, {})[probe_name] = result

    scored: list[tuple] = []
    fallback: list[str] = []

    for model, probe_results in matrix.items():
        basic = probe_results.get("basic_chat")
        if not (basic and basic.supported):
            fallback.append(model)
            continue
        supp = sum(1 for r in probe_results.values() if r.supported)
        high = sum(
            1 for r in probe_results.values()
            if r.supported and getattr(r, "response_health", None) == "healthy"
        )
        lat = basic.latency_ms if basic.latency_ms is not None else 1e9
        scored.append((model, supp, high, lat))

    scored.sort(key=lambda r: (-r[1], -r[2], r[3]))
    ranked = [m for m, *_ in scored]

    # 若 scored 不足 top_n，用 fallback 补齐
    if len(ranked) < top_n:
        for m in fallback:
            if m not in ranked:
                ranked.append(m)

    return ranked[:top_n]


# ──────────────────────────────────────────────────────────────────────────
# Stage4：边界探测
# ──────────────────────────────────────────────────────────────────────────


class Stage4_LimitsDetection:
    """Stage4：边界探测。

    对排名前 top_n 的可用模型逐一探测：
        1. max_tokens：最大输出 token 数（从大到小尝试候选列表）
        2. max_context_length：最大输入上下文（字符近似，从小到大探测）
        3. rate_limit_rpm：从响应头读取 RPM 限制

    产出写入 ctx.limits（LimitsResult.per_model）。
    """

    MAX_TOKENS_CANDIDATES = [65536, 16384, 8192, 4096]
    CONTEXT_CHAR_CANDIDATES = [4000, 16000, 64000, 128000]

    def __init__(self, adapter_registry, top_n: int = 3):
        self._adapter_registry = adapter_registry
        self._top_n = top_n

    @property
    def stage_number(self) -> int:
        return 4

    @property
    def stage_name(self) -> str:
        return "边界探测"

    async def run(self, ctx: ProbeContext) -> None:
        from ..models import LimitsResult, ModelLimits
        from ..secret import SecretResolver

        if not ctx.format_detection:
            raise StageExecutionError("Stage4 依赖 Stage1 格式识别结果")

        adapter = self._adapter_registry.get(ctx.format_detection.detected_format)
        if not adapter:
            raise StageExecutionError(
                f"未找到格式适配器: {ctx.format_detection.detected_format}"
            )

        models = _rank_top_models(ctx, self._top_n)
        if not models:
            ctx.limits = LimitsResult()
            return

        platform = ctx.platform
        base_url = normalize_base_url(str(platform.base_url))
        api_key = SecretResolver.resolve(platform.api_key)
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

        per_model: dict[str, ModelLimits] = {}
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(20.0, connect=5.0)
        ) as client:
            for model in models:
                # 评估模型通道兼容性
                basic_key = f"{model}:basic_chat"
                stream_key = f"{model}:streaming"
                
                support_non_stream = False
                if basic_key in ctx.capabilities:
                    support_non_stream = ctx.capabilities[basic_key].supported is True
                
                support_stream = False
                if stream_key in ctx.capabilities:
                    support_stream = ctx.capabilities[stream_key].supported is True

                # 1. max_tokens 探测：不支持非流式则直接短路
                if not support_non_stream:
                    max_tokens = "不支持非流式通道"
                else:
                    max_tokens = await self._probe_max_tokens(
                        client, base_url, headers, model, adapter
                    )
                    if max_tokens is None:
                        max_tokens = "探测超时/异常"

                # 2. max_context 探测：非流式不可用时 fallback 使用流式
                if not support_non_stream:
                    if support_stream:
                        max_context = await self._probe_max_context(
                            client, base_url, headers, model, adapter, use_stream=True
                        )
                        if max_context is None:
                            max_context = "仅流式-探测超时/异常"
                    else:
                        max_context = "模型不可用/不支持流式"
                else:
                    max_context = await self._probe_max_context(
                        client, base_url, headers, model, adapter, use_stream=False
                    )
                    if max_context is None:
                        max_context = "探测超时/异常"

                # 3. rate_limit_rpm 探测：压测支持自适应流式
                rate_limit_rpm, rate_limit_source = await self._probe_rate_limit_rpm(
                    client, base_url, headers, model, adapter, ctx, use_stream=(not support_non_stream and support_stream)
                )

                per_model[model] = ModelLimits(
                    max_tokens=max_tokens,
                    max_context_length=max_context,
                    rate_limit_rpm=rate_limit_rpm,
                    rate_limit_source=rate_limit_source,
                )

        ctx.limits = LimitsResult(per_model=per_model)

    async def _probe_max_tokens(
        self, client, base_url, headers, model, adapter
    ) -> int | None:
        """从大到小尝试 max_tokens，返回第一个成功的值。"""
        for tokens in self.MAX_TOKENS_CANDIDATES:
            body = adapter.build_probe_request(
                "Say one word.", model, max_tokens=tokens
            )
            try:
                resp = await client.post(
                    f"{base_url}/chat/completions", json=body, headers=headers, timeout=10.0
                )
                if resp.status_code == 200:
                    return tokens
                else:
                    # 较大参数请求报错时，不要直接 break，而是 continue 降级尝试更小值
                    continue
            except Exception:
                # 异常时同样 continue 降级尝试更小值
                continue
        return None

    async def _probe_max_context(
        self, client, base_url, headers, model, adapter, use_stream: bool = False
    ) -> int | None:
        """从小到大发送越来越长的 prompt，返回最后一个成功的字符数。"""
        max_found = None
        filler = "hello "
        for char_count in self.CONTEXT_CHAR_CANDIDATES:
            repeat_n = char_count // len(filler)
            prompt = (filler * repeat_n)[:char_count] + " Reply with one word."
            body = adapter.build_probe_request(prompt, model, max_tokens=1)
            if use_stream:
                body["stream"] = True
            try:
                if use_stream:
                    # 对于流式 fallback，使用 client.stream 进行首包与状态码判定
                    async with client.stream(
                        "POST", f"{base_url}/chat/completions", json=body, headers=headers, timeout=15.0
                    ) as resp:
                        if resp.status_code == 200:
                            max_found = char_count
                        elif resp.status_code == 400:
                            break
                        else:
                            break
                else:
                    resp = await client.post(
                        f"{base_url}/chat/completions", json=body, headers=headers, timeout=15.0
                    )
                    if resp.status_code == 200:
                        max_found = char_count
                    elif resp.status_code == 400:
                        try:
                            msg = str(resp.json()).lower()
                            if any(
                                kw in msg
                                for kw in ("context", "token", "length", "exceed")
                            ):
                                break
                        except Exception:
                            pass
                        break
                    else:
                        break
            except Exception:
                break
        return max_found

    async def _probe_rate_limit_from_header(
        self, client, base_url, headers, model, adapter, use_stream: bool = False
    ) -> int | None:
        """从响应头提取每分钟请求数限制。"""
        body = adapter.build_probe_request("Hi", model, max_tokens=1)
        if use_stream:
            body["stream"] = True
        try:
            if use_stream:
                async with client.stream(
                    "POST", f"{base_url}/chat/completions", json=body, headers=headers, timeout=5.0
                ) as resp:
                    for header_name in (
                        "x-ratelimit-limit-requests",
                        "x-ratelimit-requests-limit",
                        "ratelimit-limit",
                        "x-rate-limit-limit",
                        "x-ratelimit-limit",
                    ):
                        value = resp.headers.get(header_name)
                        if value:
                            try:
                                return int(value)
                            except (ValueError, TypeError):
                                pass
            else:
                resp = await client.post(
                    f"{base_url}/chat/completions", json=body, headers=headers, timeout=5.0
                )
                for header_name in (
                    "x-ratelimit-limit-requests",
                    "x-ratelimit-requests-limit",
                    "ratelimit-limit",
                    "x-rate-limit-limit",
                    "x-ratelimit-limit",
                ):
                    value = resp.headers.get(header_name)
                    if value:
                        try:
                            return int(value)
                        except (ValueError, TypeError):
                            pass
        except Exception:
            pass
        return None

    async def _probe_rate_limit_rpm(
        self, client, base_url, headers, model, adapter, ctx: Optional[ProbeContext] = None, use_stream: bool = False
    ) -> tuple[int | None, str | None]:
        """多级自适应探测速率限制 (RPM)。
        
        第一级：从标准 HTTP 响应头提取。
        第二级：配额端点路径盲扫。
        第三级：运行期 429 报错重置反推。
        第四级：阶梯并发温和压测。
        """
        from typing import Any
        # --- 第一级：从标准 HTTP 响应头提取 ---
        val = await self._probe_rate_limit_from_header(client, base_url, headers, model, adapter, use_stream=use_stream)
        if val is not None:
            return val, "Header 提取"

        # --- 第二级：配额端点路径盲扫 ---
        paths = ["/subscription", "/key/status", "/limits", "/key", "/status"]
        urls = []
        for p in paths:
            urls.append(f"{base_url.rstrip('/')}{p}")
            if "/v1" in base_url:
                parent_url = base_url.replace("/v1", "").rstrip('/')
                urls.append(f"{parent_url}{p}")
        
        # 去重保持顺序
        seen_urls = []
        for u in urls:
            if u not in seen_urls:
                seen_urls.append(u)

        target_keys = ["rate_limit_rpm", "rpm", "requests_limit", "request_limit", "rpm_limit", "requests_per_minute"]
        
        def search_key_in_dict(data: Any, target_keys: list[str]) -> Any:
            if isinstance(data, dict):
                for tk in target_keys:
                    if tk in data:
                        return data[tk]
                for k, v in data.items():
                    if isinstance(v, (dict, list)):
                        res = search_key_in_dict(v, target_keys)
                        if res is not None:
                            return res
            elif isinstance(data, list):
                for item in data:
                    res = search_key_in_dict(item, target_keys)
                    if res is not None:
                        return res
            return None

        for url in seen_urls:
            try:
                resp = await client.get(url, headers=headers, timeout=5.0)
                if resp.status_code == 200:
                    data = resp.json()
                    quota_val = search_key_in_dict(data, target_keys)
                    if quota_val is not None:
                        try:
                            rpm_int = int(quota_val)
                            if 1 < rpm_int < 1000000:
                                return rpm_int, "端点盲扫"
                        except (ValueError, TypeError):
                            pass
            except Exception:
                pass

        # --- 第三级：运行期 429 报错重置反推 ---
        max_retry_after = 0
        if ctx and ctx.capabilities:
            for key, cap in ctx.capabilities.items():
                if key.startswith(f"{model}:"):
                    if getattr(cap, "retry_after_s", None) is not None:
                        if cap.retry_after_s > max_retry_after:
                            max_retry_after = cap.retry_after_s
        if max_retry_after > 0:
            return max(1, 60 // max_retry_after), "429 反推"

        # --- 第四级：阶梯并发温和压测 ---
        body = adapter.build_probe_request("Hi", model, max_tokens=1)
        if use_stream:
            body["stream"] = True
        
        async def send_single_lightweight_request():
            try:
                if use_stream:
                    async with client.stream(
                        "POST", f"{base_url}/chat/completions", json=body, headers=headers, timeout=5.0
                    ) as resp:
                        return resp.status_code
                else:
                    resp = await client.post(
                        f"{base_url}/chat/completions", json=body, headers=headers, timeout=5.0
                    )
                    return resp.status_code
            except Exception:
                return 500

        # 测试 2 并发
        tasks_2 = [send_single_lightweight_request() for _ in range(2)]
        results_2 = await asyncio.gather(*tasks_2)
        if 429 in results_2:
            return 10, "压测判定"
        
        await asyncio.sleep(0.2)
        
        # 测试 5 并发
        tasks_5 = [send_single_lightweight_request() for _ in range(5)]
        results_5 = await asyncio.gather(*tasks_5)
        if 429 in results_5:
            return 60, "压测判定"
        
        return 300, "压测判定"


# ──────────────────────────────────────────────────────────────────────────
# Stage5：稳定性分析
# ──────────────────────────────────────────────────────────────────────────


class Stage5_StabilityAnalysis:
    """Stage5：稳定性分析。

    对排名前 top_n 的可用模型各发送 REPEAT_TIMES 次 basic_chat 请求，
    per-model 统计成功率 / 平均延迟 / 错误模式 / 星级，
    并汇总平台整体成功率与星级。

    产出写入 ctx.stability（StabilityResult）。
    """

    REPEAT_TIMES = 5

    def __init__(self, adapter_registry, top_n: int = 3):
        self._adapter_registry = adapter_registry
        self._top_n = top_n

    @property
    def stage_number(self) -> int:
        return 5

    @property
    def stage_name(self) -> str:
        return "稳定性分析"

    async def run(self, ctx: ProbeContext) -> None:
        import time

        from ..constants import stability_stars
        from ..error_taxonomy import classify as _classify, signal_from_response
        from ..models import ModelStability, StabilityResult
        from ..secret import SecretResolver

        if not ctx.format_detection:
            raise StageExecutionError("Stage5 依赖 Stage1 格式识别结果")

        adapter = self._adapter_registry.get(ctx.format_detection.detected_format)
        if not adapter:
            raise StageExecutionError(
                f"未找到格式适配器: {ctx.format_detection.detected_format}"
            )

        models = _rank_top_models(ctx, self._top_n)
        if not models:
            ctx.stability = StabilityResult()
            return

        platform = ctx.platform
        base_url = normalize_base_url(str(platform.base_url))
        api_key = SecretResolver.resolve(platform.api_key)
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

        semaphore = asyncio.Semaphore(3)

        # per-model 收集结构：{model: {"success": int, "latencies": [], "errors": []}}
        model_stats: dict[str, dict] = {
            m: {"success": 0, "total": 0, "latencies": [], "errors": []}
            for m in models
        }

        async def _single_probe(model: str) -> None:
            body = adapter.build_probe_request("Hello", model, max_tokens=5)
            async with semaphore:
                async with httpx.AsyncClient(
                    timeout=httpx.Timeout(20.0, connect=5.0)
                ) as client:
                    t0 = time.time()
                    try:
                        resp = await client.post(
                            f"{base_url}/chat/completions",
                            json=body,
                            headers=headers,
                        )
                        latency_ms = (time.time() - t0) * 1000
                        model_stats[model]["total"] += 1
                        if resp.status_code == 200:
                            model_stats[model]["success"] += 1
                            model_stats[model]["latencies"].append(latency_ms)
                        else:
                            sig = signal_from_response(resp, platform_name=platform.name)
                            diagnosis = _classify(sig)
                            model_stats[model]["errors"].append(diagnosis.unavailable_reason)
                    except Exception as e:
                        model_stats[model]["total"] += 1
                        model_stats[model]["errors"].append(
                            f"network_error:{type(e).__name__}"
                        )

        tasks = [
            _single_probe(m)
            for m in models
            for _ in range(self.REPEAT_TIMES)
        ]
        await asyncio.gather(*tasks, return_exceptions=True)

        # 汇总 per-model 结果
        per_model: dict[str, ModelStability] = {}
        platform_success = 0
        platform_total = 0

        for model in models:
            stats = model_stats[model]
            total = stats["total"] or self.REPEAT_TIMES  # 防止除零
            success = stats["success"]
            rate = success / total
            avg_lat = (
                sum(stats["latencies"]) / len(stats["latencies"])
                if stats["latencies"] else 0.0
            )
            # 去重保序
            seen: set[str] = set()
            unique_errors: list[str] = []
            for p in stats["errors"]:
                if p not in seen:
                    seen.add(p)
                    unique_errors.append(p)

            per_model[model] = ModelStability(
                success_rate=rate,
                avg_latency_ms=avg_lat,
                star_rating=stability_stars(rate),
                error_patterns=unique_errors,
            )
            platform_success += success
            platform_total += total

        platform_rate = platform_success / platform_total if platform_total else 0.0

        ctx.stability = StabilityResult(
            per_model=per_model,
            platform_success_rate=platform_rate,
            platform_star_rating=stability_stars(platform_rate),
        )
