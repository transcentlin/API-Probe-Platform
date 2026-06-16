# -*- coding: utf-8 -*-
"""probe_runner.py：提取的可复用探测运行函数（CLI 与 Web 共用）。"""

import asyncio
from datetime import datetime
from pathlib import Path
from typing import Any

from .adapters.base import AdapterRegistry, OpenAIAdapter
from .analyzer import ResultAnalyzer
from .constants import ProbeMode
from .engine.engine import ProbeEngine
from .engine.stages import (
    Stage0_Preflight,
    Stage1_FormatDetection,
    Stage2_EndpointDiscovery,
    Stage2_5_ModelAvailabilityCheck,
    Stage3_CapabilityProbing,
    Stage4_LimitsDetection,
    Stage5_StabilityAnalysis,
)
from .models import ProbeContext, PlatformConfig, ProbeTimeouts
from .reporter import ReportGenerator
from .scheduler import PlatformRunResult
from .secret import SecretResolver
from .probes.basic_chat import BasicChatProbe
from .probes.streaming import StreamingProbe
from .probes.tool_calling import ToolCallingProbe
from .probes.vision import VisionProbe
from .probes.json_mode import JsonModeProbe
from .probes.reasoning import ReasoningProbe
from .probes.web_search import WebSearchProbe
from .probes.multi_turn import MultiTurnProbe


async def run_platform_probe(
    platform: PlatformConfig,
    mode: str,
    probe_timeouts: ProbeTimeouts,
    deep_top_n: int,
    reports_dir: Path,
) -> PlatformRunResult:
    """执行单个平台的完整探测流程（CLI 和 Web 共用）。

    Args:
        platform: 平台配置对象
        mode: 探测模式 (standard / deep)
        probe_timeouts: 超时参数
        deep_top_n: 深度探测时覆盖前 N 个模型
        reports_dir: 报告输出目录

    Returns:
        PlatformRunResult 运行结果
    """
    # 动态解析 base_url (如果支持 ${VAR} 引用，例如兼容旧的 yaml)
    base_url = platform.base_url
    if base_url.startswith("${") and base_url.endswith("}"):
        try:
            base_url = SecretResolver.resolve(base_url)
        except Exception as e:
            return PlatformRunResult(
                name=platform.name,
                success=False,
                error_message=f"Base URL 密钥解析失败: {e}",
            )
            
    # 解析 api_key
    try:
        api_key = SecretResolver.resolve(platform.api_key)
    except Exception as e:
        return PlatformRunResult(
            name=platform.name,
            success=False,
            error_message=f"API Key 密钥解析失败: {e}",
        )

    # 将展开后的 base_url 和 api_key 写回 platform 拷贝对象中
    platform = platform.model_copy(update={"base_url": base_url, "api_key": api_key})

    print(f"  - base_url: {platform.base_url}")
    print(f"  - api_key:  {SecretResolver.mask(api_key)}")
    print(
        f"  - 响应阈值: fast={probe_timeouts.fast_threshold_ms}ms, "
        f"slow={probe_timeouts.slow_threshold_ms}ms, "
        f"connect={probe_timeouts.connect_timeout_s}s"
    )

    # 初始化探测引擎
    adapter_registry = AdapterRegistry()
    adapter_registry.register("openai_chat_completions", OpenAIAdapter())

    probes = [
        BasicChatProbe(timeouts=probe_timeouts),
        StreamingProbe(timeouts=probe_timeouts),
        ToolCallingProbe(timeouts=probe_timeouts),
        VisionProbe(timeouts=probe_timeouts),
        JsonModeProbe(timeouts=probe_timeouts),
        ReasoningProbe(timeouts=probe_timeouts),
        WebSearchProbe(timeouts=probe_timeouts),
        MultiTurnProbe(timeouts=probe_timeouts),
    ]
    stages = [
        Stage0_Preflight(),
        Stage1_FormatDetection(adapter_registry),
        Stage2_EndpointDiscovery(),
        Stage2_5_ModelAvailabilityCheck(adapter_registry),
        Stage3_CapabilityProbing(probes, adapter_registry),
        Stage4_LimitsDetection(adapter_registry, top_n=deep_top_n),
        Stage5_StabilityAnalysis(adapter_registry, top_n=deep_top_n),
    ]
    engine = ProbeEngine(stages)

    ctx = ProbeContext(platform=platform, mode=mode)
    ctx = await engine.probe_platform(ctx)

    # 生成报告
    analyzer = ResultAnalyzer()
    analyzer.analyze_model_availability(ctx)
    reporter = ReportGenerator(analyzer, timeouts=probe_timeouts)
    report_md = reporter.generate_platform_report(ctx)

    reports_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%y%m%d_%H%M")
    out_path = reports_dir / f"{ctx.platform.name}_探测报告_{stamp}.md"
    out_path.write_text(report_md, encoding="utf-8")

    return PlatformRunResult(
        name=platform.name,
        success=True,
        report_path=str(out_path),
    )
