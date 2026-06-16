"""单元测试：PlatformScheduler（多平台调度）。"""
from __future__ import annotations

import asyncio
import time

import pytest

from api_probe_system.core.scheduler import (
    PlatformRunResult,
    PlatformScheduler,
    SchedulerSummary,
)


# ──────────────────────────────────────────────────────────────────
# 串行
# ──────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_serial_runs_in_order():
    """串行：N 个平台按顺序执行，返回结果顺序与输入一致。"""
    call_order: list[str] = []

    async def worker(name: str) -> PlatformRunResult:
        call_order.append(name)
        return PlatformRunResult(name=name, success=True, report_path=f"/r/{name}.md")

    scheduler = PlatformScheduler(worker)
    summary = await scheduler.run_serial(["A", "B", "C"])

    assert call_order == ["A", "B", "C"]
    assert summary.total == 3
    assert summary.succeeded == 3
    assert summary.failed == 0
    assert [r.name for r in summary.results] == ["A", "B", "C"]


@pytest.mark.asyncio
async def test_serial_continues_on_failure():
    """一个平台抛异常时，其余平台仍继续。"""
    async def worker(name: str) -> PlatformRunResult:
        if name == "B":
            raise RuntimeError("simulated crash")
        return PlatformRunResult(name=name, success=True)

    scheduler = PlatformScheduler(worker)
    summary = await scheduler.run_serial(["A", "B", "C"])

    assert summary.total == 3
    assert summary.succeeded == 2
    assert summary.failed == 1
    failed_results = [r for r in summary.results if not r.success]
    assert len(failed_results) == 1
    assert failed_results[0].name == "B"
    assert "RuntimeError" in failed_results[0].error_message


# ──────────────────────────────────────────────────────────────────
# 并行
# ──────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_parallel_faster_than_serial():
    """并行：N 个平台同时启动，总耗时显著小于串行。"""
    DELAY = 0.3  # 每个 worker 睡 0.3s

    async def slow_worker(name: str) -> PlatformRunResult:
        await asyncio.sleep(DELAY)
        return PlatformRunResult(name=name, success=True)

    scheduler = PlatformScheduler(slow_worker)

    t0 = time.monotonic()
    summary = await scheduler.run_parallel(["A", "B", "C", "D"])
    elapsed = time.monotonic() - t0

    assert summary.succeeded == 4
    # 并行：总耗时应远小于串行的 4*DELAY=1.2s
    assert elapsed < DELAY * 2, f"并行总耗时 {elapsed:.2f}s 应 < {DELAY*2}s"


@pytest.mark.asyncio
async def test_parallel_handles_mixed_outcomes():
    """并行：成功失败混合，都能被统计。"""
    async def worker(name: str) -> PlatformRunResult:
        if name in ("X", "Y"):
            raise ValueError(f"crashed {name}")
        return PlatformRunResult(name=name, success=True)

    scheduler = PlatformScheduler(worker)
    summary = await scheduler.run_parallel(["A", "X", "B", "Y"])
    assert summary.total == 4
    assert summary.succeeded == 2
    assert summary.failed == 2


# ──────────────────────────────────────────────────────────────────
# SchedulerSummary
# ──────────────────────────────────────────────────────────────────

def test_summary_from_results():
    results = [
        PlatformRunResult(name="A", success=True),
        PlatformRunResult(name="B", success=False, error_message="x"),
        PlatformRunResult(name="C", success=True),
    ]
    s = SchedulerSummary.from_results(results)
    assert s.total == 3
    assert s.succeeded == 2
    assert s.failed == 1
    assert s.results == results
