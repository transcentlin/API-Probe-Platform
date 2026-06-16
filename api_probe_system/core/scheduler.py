"""PlatformScheduler：多平台调度器（串行 / 并行）。

职责：
    - 接收平台名列表 + 探测函数 worker
    - 串行：依次调用 worker(name)，前一个完成再开下一个
    - 并行：asyncio.gather，所有平台同时启动

约定：
    worker(platform_name: str) -> "PlatformRunResult"
    每个 worker 自己负责：
        - 用 ConfigManager.get_platform(name) 取配置
        - 构造 ProbeEngine + 跑完整流程
        - 生成 Markdown 报告
        - 返回 PlatformRunResult（成功/失败 + 报告路径）

scheduler 只关心调度，不关心探测细节。
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Awaitable, Callable, Optional


@dataclass
class PlatformRunResult:
    """单平台探测结果。"""
    name: str
    success: bool
    report_path: Optional[str] = None
    error_message: Optional[str] = None
    duration_seconds: float = 0.0


@dataclass
class SchedulerSummary:
    """调度汇总。"""
    total: int = 0
    succeeded: int = 0
    failed: int = 0
    results: list[PlatformRunResult] = field(default_factory=list)

    @classmethod
    def from_results(cls, results: list[PlatformRunResult]) -> "SchedulerSummary":
        return cls(
            total=len(results),
            succeeded=sum(1 for r in results if r.success),
            failed=sum(1 for r in results if not r.success),
            results=results,
        )


# Worker 签名：异步函数，输入平台名，输出 PlatformRunResult
PlatformWorker = Callable[[str], Awaitable[PlatformRunResult]]


class PlatformScheduler:
    """多平台调度器。"""

    def __init__(self, worker: PlatformWorker):
        """
        Args:
            worker: 单平台探测异步函数，签名为 worker(platform_name) -> PlatformRunResult
        """
        self._worker = worker

    async def run_serial(self, names: list[str]) -> SchedulerSummary:
        """串行执行。一个完成再开下一个。"""
        results: list[PlatformRunResult] = []
        for i, name in enumerate(names, start=1):
            print()
            print("=" * 70)
            print(f"  [{i}/{len(names)}] 开始探测平台：{name}")
            print("=" * 70)
            result = await self._run_safe(name)
            results.append(result)
            self._print_result_summary(result)
        return SchedulerSummary.from_results(results)

    async def run_parallel(self, names: list[str]) -> SchedulerSummary:
        """并行执行。所有平台同时启动。"""
        print()
        print("=" * 70)
        print(f"  并行启动 {len(names)} 个平台：{', '.join(names)}")
        print("=" * 70)
        tasks = [self._run_safe(name) for name in names]
        results = await asyncio.gather(*tasks)
        for r in results:
            self._print_result_summary(r)
        return SchedulerSummary.from_results(list(results))

    async def _run_safe(self, name: str) -> PlatformRunResult:
        """单平台兜底执行：任何异常都转成失败结果，不影响其他平台。"""
        import time
        start = time.monotonic()
        try:
            result = await self._worker(name)
            result.duration_seconds = time.monotonic() - start
            return result
        except Exception as e:
            import traceback
            tb = traceback.format_exc()
            print(f"\n[ERROR] 平台 {name} 探测异常: {e}")
            print(tb)
            return PlatformRunResult(
                name=name,
                success=False,
                error_message=f"{type(e).__name__}: {e}",
                duration_seconds=time.monotonic() - start,
            )

    @staticmethod
    def _print_result_summary(r: PlatformRunResult) -> None:
        status = "[OK]  " if r.success else "[FAIL]"
        print(f"\n  {status} {r.name}  耗时 {r.duration_seconds:.1f}s")
        if r.success and r.report_path:
            print(f"         报告：{r.report_path}")
        if not r.success and r.error_message:
            print(f"         错误：{r.error_message}")
