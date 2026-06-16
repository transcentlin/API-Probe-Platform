"""ProbeEngine：探测引擎编排器（详细设计 §2.3）。

职责：
    1. 编排 6 阶段执行（M1 实现 Stage0/1/2）
    2. 阶段容错：捕获异常记录到 ctx.failures，不中断流程
    3. 上下文传递：各阶段产出写入 ProbeContext，后续阶段读取
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from ..constants import PROBE_MODE_STAGES, StageExecutionError
from ..models import ProbeContext

if TYPE_CHECKING:
    from .stages import Stage


class ProbeEngine:
    """探测引擎（详细设计 §2.3）。"""

    def __init__(self, stages: list[Stage]):
        """初始化探测引擎。

        Args:
            stages: 阶段实例列表（按编号 0~5 排序）
        """
        # 使用 stage_name 作为键，支持同编号的多个阶段（如 Stage2 和 Stage2.5）
        self._stages_by_number = {}
        self._stages_by_name = {}

        for stage in stages:
            stage_num = stage.stage_number
            stage_name = stage.stage_name

            # 按编号存储（支持多个同编号阶段）
            if stage_num not in self._stages_by_number:
                self._stages_by_number[stage_num] = []
            self._stages_by_number[stage_num].append(stage)

            # 按名称存储（唯一）
            self._stages_by_name[stage_name] = stage

    async def probe_platform(self, ctx: ProbeContext) -> ProbeContext:
        """对单平台执行探测（对应 FR-PROBE-01）。

        Args:
            ctx: 探测上下文（已填充 platform/mode）

        Returns:
            填充完整产出的 ProbeContext
        """
        # 确定要执行的阶段
        stage_numbers = self._get_stage_numbers(ctx.mode)

        # 依次执行各阶段
        for stage_num in stage_numbers:
            stages = self._stages_by_number.get(stage_num)
            if not stages:
                # 阶段未实现（如 Stage4/5 在 M2 未实现）
                continue

            # 执行该编号下的所有阶段（如 Stage2 和 Stage2.5）
            for stage in stages:
                try:
                    await self._run_stage(stage, ctx)
                except StageExecutionError as e:
                    # 阶段失败：记录到 ctx.failures，继续后续阶段（详细设计 §6.1）
                    self._handle_stage_failure(stage, e, ctx)
                    # 关键阶段失败则中断（Stage0/1 失败后续无法继续）
                    if stage_num in (0, 1):
                        break

        return ctx

    async def _run_stage(self, stage: Stage, ctx: ProbeContext) -> None:
        """执行单阶段（详细设计 §2.3 _run_stage）。

        Args:
            stage: 阶段实例
            ctx: 探测上下文

        Raises:
            StageExecutionError: 阶段执行失败
        """
        await stage.run(ctx)

    def _handle_stage_failure(
        self, stage: Stage, error: Exception, ctx: ProbeContext
    ) -> None:
        """记录阶段失败（详细设计 §2.3 _handle_stage_failure）。

        Args:
            stage: 失败的阶段
            error: 异常对象
            ctx: 探测上下文
        """
        ctx.add_failure(stage.stage_number, error)

    def _get_stage_numbers(self, mode: str) -> list[int]:
        """根据探测模式获取要执行的阶段编号列表。

        Args:
            mode: 探测模式（quick/standard/deep/custom）

        Returns:
            阶段编号列表
        """
        stages = PROBE_MODE_STAGES.get(mode)
        if stages is None:
            # custom 模式：默认执行所有已实现阶段（M3 为 0~5）
            return [0, 1, 2, 3, 4, 5]
        return stages
