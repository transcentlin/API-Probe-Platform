"""能力探针模块（M2 核心）。

定义 CapabilityProbe 协议和 8 个探针实现。
对应需求：FR-CAP-01~08（基础对话/流式/工具调用/视觉/JSON/推理/联网/多轮）。
"""
from __future__ import annotations

from typing import Protocol

from ..models import CapabilityResult, PlatformConfig
from ..adapters.base import FormatAdapter


class CapabilityProbe(Protocol):
    """能力探针协议（所有探针必须实现）。

    设计理念：
        每个探针负责测试一项特定能力，返回标准化的 CapabilityResult。
        探针之间相互独立，可并发执行。
    """

    @property
    def name(self) -> str:
        """探针名称（如 'basic_chat'）。

        用于：
            - 日志输出
            - ctx.capabilities 字典的键（格式："{model}:{probe.name}"）
            - 数据库 probe_requests 表的 probe_name 字段
        """
        ...

    @property
    def probe_type(self) -> str:
        """探针类型（ProbeType 枚举值）。

        用于分类和统计。
        """
        ...

    async def probe(
        self,
        platform: PlatformConfig,
        model: str,
        adapter: FormatAdapter,
        *,
        prefer_streaming: bool = False,
    ) -> CapabilityResult:
        """探测单个模型的能力。

        Args:
            platform: 平台配置（含 base_url、api_key）
            model: 模型 ID
            adapter: 格式适配器（用于构造请求和解析响应）

        Returns:
            CapabilityResult 对象（包含 supported、reliability、detail 等字段）

        Raises:
            不应抛出异常，所有错误应捕获并反映在 CapabilityResult 中。
        """
        ...


__all__ = ["CapabilityProbe"]
