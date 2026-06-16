# 修改历史 (Revision History)
# ==================================
# 版本: v1.2
# 日期: 2026-06-16
# 修改说明: 移除“部分可用”的分类统计，将其统一合并到完全可用模型中（因为只要基础对话通过即为可用，具体能力缺失在后面的能力矩阵展示），使得模型分类保持简净的两态。
# ----------------------------------
# 版本: v1.1
# 日期: 2026-06-15
# 修改说明: 在分析模型可用性时，结合 Stage3 双通道状态原地过滤 DEAD 模型，确保其从可用列表移除、正确计入不可用并在能力矩阵中剔除。
# ==================================

"""分析器模块：结果分析。

包含：
    - ModelAvailabilitySummary: 模型可用性汇总
    - ResultAnalyzer: 结果分析器（M2 实现）
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .constants import UnavailableReason, ModelAvailability
from .models import ProbeContext


# ──────────────────────────────────────────────────────────────────────────
# 错误模式识别
# ──────────────────────────────────────────────────────────────────────────


# ──────────────────────────────────────────────────────────────────────────
# 结果分析
# ──────────────────────────────────────────────────────────────────────────


@dataclass
class ModelAvailabilitySummary:
    """模型可用性汇总（M2 核心产出）。

    用于报告生成，展示平台的模型可用性概况。
    """

    platform: str
    total_models: int
    fully_available: int
    partially_available: int
    unavailable: int
    untested: int

    # 不可用模型按成因分类：{成因 → 模型列表}
    unavailable_breakdown: dict[str, list[str]] = field(default_factory=dict)

    def availability_rate(self) -> float:
        """计算可用率 = 完全可用 / 总数（部分可用已被剔除合并）。"""
        if self.total_models == 0:
            return 0.0
        return self.fully_available / self.total_models


class ResultAnalyzer:
    """结果分析器（M2 核心组件）。

    职责：
        1. 分析模型可用性汇总
        2. 生成能力矩阵（M3 实现）
        3. 识别错误模式
    """

    def __init__(self):
        """初始化分析器。"""

    def analyze_model_availability(
        self, ctx: ProbeContext
    ) -> ModelAvailabilitySummary:
        """生成模型可用性汇总。

        Args:
            ctx: 探测上下文（需要 Stage2.5 或 Stage3 的结果）

        Returns:
            ModelAvailabilitySummary 对象
        """
        platform_name = ctx.platform.name

        # 优先使用 Stage2.5 的结果
        if ctx.model_availability_check:
            # 如果有 Stage3 的双通道状态，原地修正可用与不可用模型
            if getattr(ctx, "transport_modes", None):
                from .constants import TransportMode
                available_list = list(ctx.model_availability_check.available_models)
                unavailable_dict = dict(ctx.model_availability_check.unavailable_models)
                
                modified = False
                for model in list(available_list):
                    if ctx.transport_modes.get(model) == TransportMode.DEAD.value:
                        available_list.remove(model)
                        
                        # 提取 Stage3 里的失败原因
                        bc_result = ctx.capabilities.get(f"{model}:basic_chat")
                        reason = UnavailableReason.UNKNOWN.value
                        err_msg = "基础对话与流式探测均失败"
                        status_code = None
                        if bc_result:
                            reason = bc_result.unavailable_reason or UnavailableReason.UNKNOWN.value
                            err_msg = bc_result.error_message or bc_result.detail or "基础对话与流式探测均失败"
                            status_code = bc_result.error_code
                            
                        unavailable_dict[model] = {
                            "reason": reason,
                            "error": err_msg,
                            "status_code": status_code,
                        }
                        modified = True
                
                if modified:
                    ctx.model_availability_check.available_models = available_list
                    ctx.model_availability_check.unavailable_models = unavailable_dict

            total_models = (
                len(ctx.model_availability_check.available_models)
                + len(ctx.model_availability_check.unavailable_models)
            )

            # 按成因分类不可用模型
            unavailable_breakdown = {}
            for model, info in ctx.model_availability_check.unavailable_models.items():
                reason = info.get("reason", UnavailableReason.UNKNOWN.value)
                if reason not in unavailable_breakdown:
                    unavailable_breakdown[reason] = []
                unavailable_breakdown[reason].append(model)

            return ModelAvailabilitySummary(
                platform=platform_name,
                total_models=total_models,
                fully_available=len(ctx.model_availability_check.available_models),
                partially_available=0,  # Stage2.5 不区分部分可用
                unavailable=len(ctx.model_availability_check.unavailable_models),
                untested=0,
                unavailable_breakdown=unavailable_breakdown,
            )

        # 回退：使用 Stage3 的 BasicChatProbe 结果
        if ctx.endpoint_discovery and ctx.capabilities:
            models = ctx.endpoint_discovery.models
            summary = ModelAvailabilitySummary(
                platform=platform_name,
                total_models=len(models),
                fully_available=0,
                partially_available=0,
                unavailable=0,
                untested=0,
            )

            for model in models:
                basic_chat_key = f"{model}:basic_chat"
                result = ctx.capabilities.get(basic_chat_key)

                if not result:
                    summary.untested += 1
                elif (
                    result.availability == ModelAvailability.FULLY_AVAILABLE.value
                    or result.availability == ModelAvailability.PARTIALLY_AVAILABLE.value
                ):
                    summary.fully_available += 1
                elif result.availability == ModelAvailability.UNAVAILABLE.value:
                    summary.unavailable += 1

                    # 按成因分类
                    reason = result.unavailable_reason or UnavailableReason.UNKNOWN.value
                    if reason not in summary.unavailable_breakdown:
                        summary.unavailable_breakdown[reason] = []
                    summary.unavailable_breakdown[reason].append(model)

            return summary

        # 无可用数据
        return ModelAvailabilitySummary(
            platform=platform_name,
            total_models=0,
            fully_available=0,
            partially_available=0,
            unavailable=0,
            untested=0,
        )
