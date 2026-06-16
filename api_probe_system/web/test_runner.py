# 修改历史 (Revision History)
# ==================================
# 版本: v1.2.0
# 日期: 2026-06-16
# 修改说明: 1) 新增探测历史日志记录，在探测任务开始、成功、失败分支中更新 reports/probe_history.json；2) 在任务异常中断时，动态生成《探测异常中断报告》Markdown，避免失败时无报告落盘。
# ----------------------------------
# 版本: v1.1.2
# 日期: 2026-06-16
# 修改说明: 在探测执行任务前后计算总探测执行耗时，并回填至 ctx 中以渲染进 Markdown 报告。
# ----------------------------------
# 版本: v1.1.1
# 日期: 2026-06-16
# 修改说明: 修复在初始化 timeouts 和 deep_top_n 参数时错误调用 config_mgr.defaults 导致的 AttributeError，改用官方公开 of get_probe_timeouts() 及 get_deep_probe_top_n() 接口。
# ----------------------------------
# 版本: v1.1.0
# 日期: 2026-06-15
# 修改说明: 在测试结束 completed 广播事件中，实时解析生成的报告并注入评分 score 字段。
# ----------------------------------
# 版本: v1.0.0
# 日期: 2026-06-15
# 修改说明: 实现 Web 异步测试执行管理器 (TestRunner)，包含 SSE 事件发布订阅器与基于包装器模式的 Stage 推送器。
# ==================================

# -*- coding: utf-8 -*-
import asyncio
import logging
import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional, Any

from api_probe_system.core.adapters.base import AdapterRegistry, OpenAIAdapter
from api_probe_system.core.analyzer import ResultAnalyzer
from api_probe_system.core.engine.engine import ProbeEngine
from api_probe_system.core.engine.stages import (
    Stage0_Preflight,
    Stage1_FormatDetection,
    Stage2_EndpointDiscovery,
    Stage2_5_ModelAvailabilityCheck,
    Stage3_CapabilityProbing,
    Stage4_LimitsDetection,
    Stage5_StabilityAnalysis,
)
from api_probe_system.core.models import ProbeContext, PlatformConfig, ProbeTimeouts
from api_probe_system.core.reporter import ReportGenerator
from api_probe_system.core.scheduler import PlatformRunResult
from api_probe_system.core.secret import SecretResolver
from api_probe_system.core.probes.basic_chat import BasicChatProbe
from api_probe_system.core.probes.streaming import StreamingProbe
from api_probe_system.core.probes.tool_calling import ToolCallingProbe
from api_probe_system.core.probes.vision import VisionProbe
from api_probe_system.core.probes.json_mode import JsonModeProbe
from api_probe_system.core.probes.reasoning import ReasoningProbe
from api_probe_system.core.probes.web_search import WebSearchProbe
from api_probe_system.core.probes.multi_turn import MultiTurnProbe
from api_probe_system.core.platform_manager import PlatformManager
from api_probe_system.core.report_parser import ReportParser
from api_probe_system.core.scoring import PlatformScorer

logger = logging.getLogger("api_probe_system.web.test_runner")

def _append_probe_history(
    project_root: str,
    task_id: str,
    platform_name: str,
    mode: str,
    status: str,
    message: str,
    report_filename: Optional[str] = None,
    score: Optional[int] = None
):
    """追加或更新探测历史记录，并限制日志长度不超过 200 条。"""
    try:
        reports_dir = Path(project_root) / "reports"
        reports_dir.mkdir(parents=True, exist_ok=True)
        history_file = reports_dir / "probe_history.json"
        
        history = []
        if history_file.exists():
            try:
                history = json.loads(history_file.read_text(encoding="utf-8"))
            except Exception:
                history = []
                
        # 寻找是否已有相同 task_id 的记录
        existing_idx = -1
        for idx, item in enumerate(history):
            if item.get("task_id") == task_id:
                existing_idx = idx
                break
                
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        if existing_idx != -1:
            # 更新已有任务的状态
            history[existing_idx].update({
                "status": status,
                "message": message,
                "end_time": now_str if status in ("success", "failed") else None,
                "report_filename": report_filename or history[existing_idx].get("report_filename"),
                "score": score if score is not None else history[existing_idx].get("score")
            })
        else:
            # 插入新纪录
            history.insert(0, {
                "task_id": task_id,
                "platform_name": platform_name,
                "mode": mode,
                "start_time": now_str,
                "end_time": now_str if status in ("success", "failed") else None,
                "status": status,
                "message": message,
                "report_filename": report_filename,
                "score": score
            })
            
        # Housekeeping: 仅保留最近的 200 条记录
        if len(history) > 200:
            history = history[:200]
            
        history_file.write_text(json.dumps(history, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as err:
        logger.error(f"更新探测历史日志失败: {err}")

class EventPublisher:
    """实时事件发布订阅器（用于 SSE 广播）。"""
    def __init__(self):
        self._subscribers: set[asyncio.Queue] = set()

    def subscribe(self) -> asyncio.Queue:
        q = asyncio.Queue()
        self._subscribers.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue):
        self._subscribers.discard(q)

    async def publish(self, data: dict):
        if not self._subscribers:
            return
        # 并发向所有订阅队列投放消息
        for q in list(self._subscribers):
            try:
                await q.put(data)
            except Exception as e:
                logger.error(f"SSE 广播投放失败: {e}")


class WebStageWrapper:
    """Stage 装饰器：在阶段执行前后自动触发事件广播。"""
    def __init__(self, original_stage, platform_name: str, publisher: EventPublisher):
        self.original_stage = original_stage
        self.platform_name = platform_name
        self.publisher = publisher

    @property
    def stage_number(self) -> int:
        return self.original_stage.stage_number

    @property
    def stage_name(self) -> str:
        return self.original_stage.stage_name

    async def run(self, ctx: ProbeContext) -> None:
        await self.publisher.publish({
            "platform": self.platform_name,
            "stage": self.original_stage.stage_name,
            "stage_number": self.original_stage.stage_number,
            "status": "running",
            "message": f"开始探测阶段: {self.original_stage.stage_name}"
        })
        try:
            await self.original_stage.run(ctx)
            await self.publisher.publish({
                "platform": self.platform_name,
                "stage": self.original_stage.stage_name,
                "stage_number": self.original_stage.stage_number,
                "status": "success",
                "message": f"阶段 {self.original_stage.stage_name} 执行完毕"
            })
        except Exception as e:
            await self.publisher.publish({
                "platform": self.platform_name,
                "stage": self.original_stage.stage_name,
                "stage_number": self.original_stage.stage_number,
                "status": "failed",
                "message": f"阶段 {self.original_stage.stage_name} 出错: {e}"
            })
            raise e


class WebTestRunner:
    """异步探测执行调度器。"""
    def __init__(self):
        self.active_tasks: dict[str, asyncio.Task] = {}
        self.publisher = EventPublisher()

    def is_running(self, platform_name: str) -> bool:
        return platform_name in self.active_tasks

    def start_test(
        self,
        platform_name: str,
        mode: str,
        pm: PlatformManager,
        config_mgr: Any
    ) -> bool:
        """启动特定平台的异步探测任务，若已在运行则返回 False。"""
        if self.is_running(platform_name):
            return False

        task_id = f"{platform_name}_{datetime.now().strftime('%Y%m%d%H%M%S')}_{uuid.uuid4().hex[:6]}"
        task = asyncio.create_task(
            self._run_probe_task(task_id, platform_name, mode, pm, config_mgr)
        )
        self.active_tasks[platform_name] = task
        # 绑定清理回调
        task.add_done_callback(lambda t: self.active_tasks.pop(platform_name, None))
        return True

    async def _run_probe_task(
        self,
        task_id: str,
        platform_name: str,
        mode: str,
        pm: PlatformManager,
        config_mgr: Any
    ):
        """执行单个平台 Web 嗅探的完整协程。"""
        # 记录初始运行状态
        _append_probe_history(
            project_root=config_mgr.project_root,
            task_id=task_id,
            platform_name=platform_name,
            mode=mode,
            status="running",
            message=f"启动对平台 {platform_name} 的 {mode} 模式探测任务"
        )

        await self.publisher.publish({
            "platform": platform_name,
            "stage": "System",
            "stage_number": -1,
            "status": "started",
            "message": f"启动对平台 {platform_name} 的 {mode} 模式探测任务"
        })

        try:
            entry = pm.get_platform(platform_name)
            platform = pm.to_platform_config(entry)
            
            # 解析 Key 和 base_url
            base_url = platform.base_url
            if base_url.startswith("${") and base_url.endswith("}"):
                base_url = SecretResolver.resolve(base_url)
            api_key = SecretResolver.resolve(platform.api_key)
            platform = platform.model_copy(update={"base_url": base_url, "api_key": api_key})

            # 超时和默认参数
            timeouts = config_mgr.get_probe_timeouts()
            deep_top_n = config_mgr.get_deep_probe_top_n()
            reports_dir = Path(config_mgr.project_root) / "reports"

            # 注册适配器
            adapter_registry = AdapterRegistry()
            # 内部会自动使用默认注册，这里手动把标准 openai_chat_completions 加进去
            adapter_registry.register("openai_chat_completions", OpenAIAdapter())

            # 实例化探针
            probes = [
                BasicChatProbe(timeouts=timeouts),
                StreamingProbe(timeouts=timeouts),
                ToolCallingProbe(timeouts=timeouts),
                VisionProbe(timeouts=timeouts),
                JsonModeProbe(timeouts=timeouts),
                ReasoningProbe(timeouts=timeouts),
                WebSearchProbe(timeouts=timeouts),
                MultiTurnProbe(timeouts=timeouts),
            ]

            # 原始 Stages 列表
            stages = [
                Stage0_Preflight(),
                Stage1_FormatDetection(adapter_registry),
                Stage2_EndpointDiscovery(),
                Stage2_5_ModelAvailabilityCheck(adapter_registry),
                Stage3_CapabilityProbing(probes, adapter_registry),
                Stage4_LimitsDetection(adapter_registry, top_n=deep_top_n),
                Stage5_StabilityAnalysis(adapter_registry, top_n=deep_top_n),
            ]

            # 用 WebStageWrapper 包装
            wrapped_stages = [
                WebStageWrapper(stage, platform_name, self.publisher)
                for stage in stages
            ]

            engine = ProbeEngine(wrapped_stages)
            ctx = ProbeContext(platform=platform, mode=mode)
            
            t_start = datetime.now()
            ctx = await engine.probe_platform(ctx)
            ctx.total_duration_s = (datetime.now() - t_start).total_seconds()

            # 分析数据并生成 Markdown 报告
            analyzer = ResultAnalyzer()
            analyzer.analyze_model_availability(ctx)
            reporter = ReportGenerator(analyzer, timeouts=timeouts)
            report_md = reporter.generate_platform_report(ctx)

            reports_dir.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now().strftime("%y%m%d_%H%M")
            out_path = reports_dir / f"{platform.name}_探测报告_{stamp}.md"
            out_path.write_text(report_md, encoding="utf-8")

            # 计算评分
            try:
                parsed_data = ReportParser.parse_file(out_path)
                score = PlatformScorer.calculate_score(parsed_data)
            except Exception as score_err:
                logger.error(f"测试完成后计算平台打分失败: {score_err}")
                score = None

            # 更新测试成功历史
            _append_probe_history(
                project_root=config_mgr.project_root,
                task_id=task_id,
                platform_name=platform_name,
                mode=mode,
                status="success",
                message=f"平台 {platform_name} 探测圆满完成，报告已生成！",
                report_filename=out_path.name,
                score=score
            )

            await self.publisher.publish({
                "platform": platform_name,
                "stage": "System",
                "stage_number": 6,
                "status": "completed",
                "message": f"平台 {platform_name} 探测圆满完成，报告已生成！",
                "report_path": str(out_path),
                "score": score
            })

        except Exception as e:
            logger.exception(f"Web 探测任务异常中断: {e}")
            
            # 生成探测异常中断报告以供前端预览查阅
            report_filename = None
            try:
                reports_dir = Path(config_mgr.project_root) / "reports"
                reports_dir.mkdir(parents=True, exist_ok=True)
                stamp = datetime.now().strftime("%y%m%d_%H%M")
                out_path = reports_dir / f"{platform_name}_探测报告_{stamp}.md"
                
                import traceback
                error_traceback = traceback.format_exc()
                
                report_md = f"""# {platform_name} 探测异常中断报告

## 📊 探测任务执行摘要
- **测试平台**: {platform_name}
- **探测模式**: {mode}
- **探测时间**: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
- **执行状态**: ❌ 异常中断
- **中断原因**: {str(e)}

## 🔍 异常详细堆栈
```python
{error_traceback}
```

## 🛠️ 排查建议
1. 请确认该平台的 API 密钥是否配置正确。
2. 请确认该平台的 base_url （接口网关）是否可以正常从本地访问。
3. 如果是在模型发现或预检阶段报错，请确认该平台是否开启并包含可用的模型。
4. 检查后台控制台错误堆栈以排查是否存在系统依赖包冲突等。
"""
                out_path.write_text(report_md, encoding="utf-8")
                report_filename = out_path.name
            except Exception as write_err:
                logger.error(f"写入探测异常中断报告失败: {write_err}")

            # 更新测试失败历史
            _append_probe_history(
                project_root=config_mgr.project_root,
                task_id=task_id,
                platform_name=platform_name,
                mode=mode,
                status="failed",
                message=f"任务执行出错中止: {e}",
                report_filename=report_filename
            )

            await self.publisher.publish({
                "platform": platform_name,
                "stage": "System",
                "stage_number": -1,
                "status": "error",
                "message": f"任务执行出错中止: {e}"
            })

# 全局单例 WebTestRunner
web_test_runner = WebTestRunner()
