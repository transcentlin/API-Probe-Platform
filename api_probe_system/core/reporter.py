# 修改历史 (Revision History)
# ==================================
# 版本: v1.12
# 日期: 2026-06-16
# 修改说明: 剔除模型可用性总览表格中的“部分可用”模型项统计，精简报告排版。
# ----------------------------------
# 版本: v1.11
# 日期: 2026-06-16
# 修改说明: 在报告 Header 头部与一、平台概览表格中引入“探测总耗时”展示，与仅代表可用性预检（Stage2.5）耗时的“预检耗时”进行区分。
# ----------------------------------
# 版本: v1.10
# 日期: 2026-06-16
# 修改说明: 在「一、平台概览」中引入打分引擎展现综合评分，并在此部分下方详细列出综合评分的具体计算公式。
# ==================================
# 版本: v1.8
# 日期: 2026-06-15
# 修改说明: 在「一、平台概览」的模型总数渲染行中，若发现方式为 fallback 并且包含底层 error_message，在表格中清晰展示该获取错误的具体成因，方便用户排查平台故障。
# ==================================
# 版本: v1.7
# 日期: 2026-06-15
# 修改说明: 重构「一、平台概览」的 API 格式行渲染，提取 scores 中所有打分置信度 >= 0.8 的 API 格式，并以 <br> 换行符分隔展示，以呈现平台支持的所有可用格式。
# ==================================
# 版本: v1.6
# 日期: 2026-06-15
# 修改说明: 重构「三、推荐模型」模块：限制推荐数量为前3名，剔除能力点阵列，替换为「支持能力详情」列（以顿号拼接中文能力名）；调整推荐过滤逻辑以支持仅流式可用模型的推荐。
# ==================================
# 版本: v1.5
# 日期: 2026-06-15
# 修改说明: 在边界探测（第七章）表格展示中，支持在 max_tokens 和 max_context_length 无法探测时展示简短斜体文字成因（避免非 int 的逗号格式化报错）。
# ==================================
# 版本: v1.4
# 日期: 2026-06-15
# 修改说明: 重构可用模型能力矩阵，彻底剔除原「传输通道」列，将「基础对话」重命名为「非流式」，且重排通道顺序（流式->非流式->其他），删除附录的传输通道说明。
# ==================================
# 版本: v1.3
# 日期: 2026-06-15
# 修改说明: 在第七部分「边界探测」表格中，新开辟「速率获取来源」一列，直观显示限流 RPM 数据是由何种级探测得出的，提高报告的合理性与清晰度。
# ==================================
# 版本: v1.2
# 日期: 2026-06-14
# 修改说明: 对第五部分「可用模型问题统计」的表格字段进行重构，新开辟「平台原始响应/详情」列记录完整报错；对应用层错误引入后置智能分类逻辑，消除「未知/未知」的问题。

"""报告生成器：将 ProbeContext 渲染为 Markdown 探测报告。

报告结构（按模板规范 reports/报告模板规范.md）：
    📊 执行摘要          仪表盘式速览
    一、平台概览          基础信息表格
    二、模型可用性总览    可用/不可用分布 + 模型列表
    三、推荐模型          Top-N 优选（仅基础对话通过的模型）
    四、可用模型能力矩阵  Stage2.5 可用模型 × 8 探针 + 各能力支持率
    五、可用模型问题统计  Stage3 失败聚合（不可用原因 + 错误类型联合）
    六、不可用模型分析    Stage2.5 不可用模型逐个成因
    七、边界探测          Stage4（未实现时展示占位）
    八、稳定性分析        Stage5（未实现时展示占位）
    九、阶段失败记录      条件显示
    附录 A               符号/阈值/错误分类参考
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from .analyzer import ModelAvailabilitySummary, ResultAnalyzer
from .constants import (
    ErrorCategory,
    ProbeType,
    ResponseHealth,
    UnavailableReason,
)
from .error_taxonomy import REASON_META, CATEGORY_META
from .models import CapabilityResult, ProbeContext, ProbeTimeouts


# 探针固定顺序（能力矩阵列顺序 + 能力点阵顺序）
PROBE_ORDER: list[str] = [
    ProbeType.STREAMING.value,
    ProbeType.BASIC_CHAT.value,
    ProbeType.TOOL_CALLING.value,
    ProbeType.VISION.value,
    ProbeType.JSON_MODE.value,
    ProbeType.REASONING.value,
    ProbeType.WEB_SEARCH.value,
    ProbeType.MULTI_TURN.value,
]

# 探针中文标签（用于能力矩阵列头）
PROBE_LABEL_CN: dict[str, str] = {
    ProbeType.STREAMING.value: "流式",
    ProbeType.BASIC_CHAT.value: "非流式",
    ProbeType.TOOL_CALLING.value: "工具调用",
    ProbeType.VISION.value: "视觉",
    ProbeType.JSON_MODE.value: "JSON",
    ProbeType.REASONING.value: "推理",
    ProbeType.WEB_SEARCH.value: "联网",
    ProbeType.MULTI_TURN.value: "多轮",
}

# 文案单源：从 error_taxonomy 导入（REASON_META / CATEGORY_META 已在文件头 import）
# 模块内部别名，保持下方代码引用不变
UNAVAILABLE_REASON_META = REASON_META
ERROR_CATEGORY_META = CATEGORY_META


# ──────────────────────────────────────────────────────────────────────────
# 工具函数
# ──────────────────────────────────────────────────────────────────────────


def _progress_bar(count: int, total: int, width: int = 24) -> str:
    """纯文本进度条，满格 width 字符。"""
    if total == 0:
        return "░" * width
    filled = max(0, min(width, round(count / total * width)))
    return "█" * filled + "░" * (width - filled)


def _display_width(s: str) -> int:
    """估算字符串终端显示宽度（中文字符按 2 计）。"""
    return sum(2 if ord(c) > 127 else 1 for c in s)


def _dot_matrix(probe_results: dict[str, CapabilityResult]) -> str:
    """8 项能力点阵：● 支持，○ 不支持，固定顺序。"""
    return "".join(
        "●" if (probe_results.get(p) and probe_results[p].supported) else "○"
        for p in PROBE_ORDER
    )


def _platform_health(reachable: bool, rate: float) -> str:
    """根据可达性 + 可用率返回健康度标签（含 emoji）。"""
    if not reachable:
        return "🔴 **异常**"
    if rate >= 0.8:
        return "🟢 **良好**"
    if rate >= 0.4:
        return "🟡 **中等**"
    return "🔴 **差**"


def _available_model_ids(ctx: ProbeContext) -> list[str]:
    """从 Stage2.5 取可用模型列表；回退到 Stage3 基础对话通过的模型。"""
    if ctx.model_availability_check:
        return list(ctx.model_availability_check.available_models)
    if ctx.capabilities:
        return [
            key.split(":", 1)[0]
            for key, r in ctx.capabilities.items()
            if key.endswith(f":{ProbeType.BASIC_CHAT.value}") and r.supported
        ]
    return []


def _build_matrix(ctx: ProbeContext) -> dict[str, dict[str, CapabilityResult]]:
    """将 ctx.capabilities 重整为 {model: {probe_name: CapabilityResult}}。"""
    matrix: dict[str, dict[str, CapabilityResult]] = {}
    for key, result in ctx.capabilities.items():
        if ":" not in key:
            continue
        model, probe_name = key.split(":", 1)
        matrix.setdefault(model, {})[probe_name] = result
    return matrix


def _symbol(result: Optional[CapabilityResult]) -> str:
    """按 response_health + reliability 渲染能力矩阵单元符号。"""
    if result is None or result.supported is None:
        return "N/A"
    if result.supported:
        if result.response_health == ResponseHealth.SLUGGISH.value:
            return "🟡"
        if result.reliability == "high":
            return "✓"
        if result.reliability == "medium":
            return "⚠"
        return "?"
    return "✗"


def _build_probe_error_text(result: CapabilityResult) -> str:
    """从探针结果中提取出错表现文本（HTTP 状态码 + 实际错误信息/detail）。"""
    parts: list[str] = []
    if result.error_code:
        parts.append(f"HTTP {result.error_code}")
    msg = result.error_message or result.detail or ""
    if msg:
        msg = msg.replace("\n", " ").strip()
        # 过滤极长的 html 错误页面
        if msg.lstrip().startswith("<!") or msg.lstrip().startswith("<html"):
            msg = "[HTML 页面响应]"
        else:
            msg = msg.replace("<", "&lt;").replace(">", "&gt;")
            if len(msg) > 1000:
                msg = msg[:1000] + "…"
        parts.append(msg)
    return ": ".join(parts)


def _score_model(probe_results: dict[str, CapabilityResult]) -> tuple[int, int]:
    """排序键：(支持数, 高可靠数)。"""
    supp = sum(1 for r in probe_results.values() if r and r.supported)
    high = sum(
        1 for r in probe_results.values()
        if r and r.supported and r.reliability == "high"
    )
    return supp, high


# ──────────────────────────────────────────────────────────────────────────
# 报告生成器
# ──────────────────────────────────────────────────────────────────────────


class ReportGenerator:
    """Markdown 探测报告生成器（按统一模板规范）。"""

    def __init__(
        self,
        analyzer: Optional[ResultAnalyzer] = None,
        timeouts: Optional[ProbeTimeouts] = None,
    ) -> None:
        self.analyzer = analyzer or ResultAnalyzer()
        self.timeouts = timeouts or ProbeTimeouts()

    def generate_platform_report(self, ctx: ProbeContext) -> str:
        """生成平台探测报告（Markdown 字符串）。

        Args:
            ctx: 已执行完的 ProbeContext（任意阶段均可，缺失部分自动跳过）。

        Returns:
            Markdown 文本。
        """
        summary = self.analyzer.analyze_model_availability(ctx)

        sections = [
            self._generate_header(ctx),
            self._generate_executive_summary(ctx, summary),
            self._generate_overview_section(ctx),
            self._generate_availability_section(ctx, summary),
            self._recommend_models(ctx),
            self._generate_capability_matrix_section(ctx),
            self._generate_available_model_issues_section(ctx),
            self._generate_unavailable_model_analysis(ctx),
            self._generate_limits_section(ctx),
            self._generate_stability_section(ctx),
            self._generate_failures_section(ctx),
            self._generate_appendix(),
        ]
        return "\n\n".join(s for s in sections if s).rstrip() + "\n"

    # ──────────────────────────────────────────────────────────────────
    # Header
    # ──────────────────────────────────────────────────────────────────

    def _generate_header(self, ctx: ProbeContext) -> str:
        stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        duration = ""
        if ctx.model_availability_check:
            d = ctx.model_availability_check.check_duration_ms / 1000
            duration += f" ｜ **预检耗时**：{d:.1f}s"
        
        total_dur = getattr(ctx, "total_duration_s", None)
        if total_dur is not None:
            duration += f" ｜ **探测总耗时**：{total_dur:.1f}s"

        return (
            f"# {ctx.platform.name} 探测报告\n\n"
            f"**生成时间**：{stamp} ｜ **探测模式**：{ctx.mode}{duration}"
        )

    # ──────────────────────────────────────────────────────────────────
    # 📊 执行摘要
    # ──────────────────────────────────────────────────────────────────

    def _generate_executive_summary(
        self, ctx: ProbeContext, summary: ModelAvailabilitySummary
    ) -> str:
        lines = ["## 📊 执行摘要", ""]

        reachable = ctx.connectivity.reachable if ctx.connectivity else True
        rate = summary.availability_rate()
        health_label = _platform_health(reachable, rate)
        top_model = self._get_top_model(ctx)
        top_str = f"`{top_model}`" if top_model else "—"

        avail_str = f"**{rate:.1%}**" if summary.total_models else "—"
        count_str = (
            f"{summary.fully_available} / {summary.total_models}"
            if summary.total_models else "—"
        )

        lines.append("| 平台健康度 | 模型可用率 | 可用 / 总数 | 推荐首选 |")
        lines.append("|:---:|:---:|:---:|:---:|")
        lines.append(f"| {health_label} | {avail_str} | {count_str} | {top_str} |")
        lines.append("")
        lines.append("**可用性分布**")
        lines.append("")
        lines.append("```")
        total = summary.total_models
        if total:
            lines.append(
                f"完全可用  {_progress_bar(summary.fully_available, total)}"
                f"  {summary.fully_available}"
                f"  ({summary.fully_available / total * 100:.1f}%)"
            )

            lines.append(
                f"不可用    {_progress_bar(summary.unavailable, total)}"
                f"  {summary.unavailable}"
                f"  ({summary.unavailable / total * 100:.1f}%)"
            )
        else:
            lines.append("暂无模型数据")
        lines.append("```")

        lines.append("")
        lines.append(f"**一句话结论**：{self._build_conclusion(ctx, summary, top_model)}")
        return "\n".join(lines)

    def _get_top_model(self, ctx: ProbeContext) -> Optional[str]:
        """获取推荐排名第一的模型名。"""
        matrix = _build_matrix(ctx)
        available = set(_available_model_ids(ctx))
        scored = []
        for model, probe_results in matrix.items():
            if available and model not in available:
                continue
            basic = probe_results.get(ProbeType.BASIC_CHAT.value)
            if not (basic and basic.supported):
                continue
            supp, high = _score_model(probe_results)
            lat = basic.latency_ms if basic.latency_ms else 1e9
            scored.append((model, supp, high, lat))
        if not scored:
            return None
        scored.sort(key=lambda r: (-r[1], -r[2], r[3]))
        return scored[0][0]

    def _build_conclusion(
        self,
        ctx: ProbeContext,
        summary: ModelAvailabilitySummary,
        top_model: Optional[str],
    ) -> str:
        parts = []
        if ctx.connectivity and ctx.connectivity.reachable:
            if ctx.format_detection:
                fmt = ctx.format_detection
                parts.append(
                    f"平台连通正常（{fmt.detected_format}，置信度 {fmt.confidence:.2f}）"
                )
            else:
                parts.append("平台连通正常")
        else:
            parts.append("平台不可达")

        if summary.total_models:
            parts.append(
                f"{summary.total_models} 个模型中 {summary.fully_available} 个可用"
            )

        if summary.unavailable_breakdown:
            reason_parts = []
            for r, models in summary.unavailable_breakdown.items():
                label = UNAVAILABLE_REASON_META.get(r, (r, "", "", ""))[0]
                reason_parts.append(f"{len(models)} 个因{label}不可用")
            parts.append("；".join(reason_parts))

        if top_model:
            matrix = _build_matrix(ctx)
            top_probes = matrix.get(top_model, {})
            supp = sum(1 for r in top_probes.values() if r and r.supported)
            parts.append(f"首选 `{top_model}`（支持 {supp}/8 能力）")

        return "，".join(parts) + "。"

    # ──────────────────────────────────────────────────────────────────
    # 一、平台概览
    # ──────────────────────────────────────────────────────────────────

    def _generate_overview_section(self, ctx: ProbeContext) -> str:
        from .scoring import PlatformScorer
        score = PlatformScorer.calculate_score_from_ctx(ctx)
        
        lines = ["## 一、平台概览", "", "| 项目 | 内容 |", "|------|------|"]
        lines.append(f"| 平台名称 | {ctx.platform.name} |")
        lines.append(f"| Base URL | `{ctx.platform.base_url}` |")
        lines.append(f"| 综合评分 | **{score} 分** / 100 |")

        if ctx.format_detection:
            fmt = ctx.format_detection
            detected_formats = []
            if fmt.scores:
                for fmt_name, score in fmt.scores.items():
                    if score >= 0.8:
                        detected_formats.append(f"`{fmt_name}`（置信度 {score:.2f}）")
            
            if detected_formats:
                lines.append(f"| API 格式 | {'<br>'.join(detected_formats)} |")
            else:
                lines.append(
                    f"| API 格式 | `{fmt.detected_format}`（置信度 {fmt.confidence:.2f}） |"
                )
        else:
            lines.append("| API 格式 | 未识别 |")

        if ctx.connectivity:
            conn = ctx.connectivity
            if conn.reachable:
                lat = f"{conn.latency_ms:.0f} ms" if conn.latency_ms else "未知"
                lines.append(f"| 可达性 | ✅ 可达（{lat}） |")
            else:
                err = conn.error or f"HTTP {conn.status_code}"
                lines.append(f"| 可达性 | ❌ 不可达（{err}） |")
        else:
            lines.append("| 可达性 | 未检测 |")

        if ctx.endpoint_discovery:
            ed = ctx.endpoint_discovery
            if len(ed.models) == 0:
                reason = ed.error_message if ed.error_message else "未返回模型列表且无默认模型"
                lines.append(
                    f"| 模型总数 | 0（获取失败，原因：{reason}） |"
                )
            elif ed.discovery_method == "fallback" and ed.error_message:
                lines.append(
                    f"| 模型总数 | {len(ed.models)}（发现方式：{ed.discovery_method}，失败原因：{ed.error_message}） |"
                )
            else:
                lines.append(
                    f"| 模型总数 | {len(ed.models)}（发现方式：{ed.discovery_method}） |"
                )
            if ed.endpoints:
                ep_parts = []
                for k, v in ed.endpoints.items():
                    try:
                        from urllib.parse import urlparse
                        path = urlparse(str(v)).path
                    except Exception:
                        path = str(v)
                    ep_parts.append(f"`{k}` `{path}`")
                lines.append(f"| 端点 | {'、'.join(ep_parts)} |")
        else:
            lines.append("| 模型总数 | 未知 |")

        if ctx.model_availability_check:
            dur = ctx.model_availability_check.check_duration_ms / 1000
            lines.append(f"| 可用性预检耗时 | {dur:.2f} 秒 |")

        total_dur = getattr(ctx, "total_duration_s", None)
        if total_dur is not None:
            lines.append(f"| 探测总耗时 | {total_dur:.2f} 秒 |")


        lines.append("")
        lines.append("> 💡 **综合评分计算公式说明**：")
        lines.append("> 综合评分（百分制） = `基础可用分 (40%)` + `性能时延分 (30%)` + `功能覆盖分 (30%)`")
        lines.append("> 1. **基础可用分**：`模型可用率 * 100`。")
        lines.append("> 2. **性能时延分**：根据推荐首选模型时延计算（≤1000ms 得 100分，1000~3000ms 线性折算扣分，3000~10000ms 得 40分，其余得 0分）。")
        lines.append("> 3. **功能覆盖分**：所有可用模型对“工具调用、视觉、JSON、推理、联网、多轮” 6 项高级能力支持率的平均得分。")
        lines.append("> *若平台不可达或无任何可用模型，系统将触发短路熔断，最终判定为 0 分。*")

        return "\n".join(lines)

    # ──────────────────────────────────────────────────────────────────
    # 二、模型可用性总览
    # ──────────────────────────────────────────────────────────────────

    def _generate_availability_section(
        self, ctx: ProbeContext, summary: ModelAvailabilitySummary
    ) -> str:
        lines = ["## 二、模型可用性总览", ""]

        if summary.total_models == 0:
            lines.append("_无模型数据_")
            return "\n".join(lines)

        total = summary.total_models

        available_models = _available_model_ids(ctx)

        unavail_models: list[str] = []
        if ctx.model_availability_check:
            unavail_models = list(ctx.model_availability_check.unavailable_models.keys())

        lines.append("| 状态 | 数量 | 占比 | 分布 | 模型列表 |")
        lines.append("|------|:---:|:---:|------|------|")

        avail_list_str = (
            "<br>".join(f"`{m}`" for m in available_models)
            if available_models else "—"
        )
        n_avail = summary.fully_available
        lines.append(
            f"| 🟢 完全可用 | {n_avail} | {n_avail / total * 100:.1f}% "
            f"| `{_progress_bar(n_avail, total)}` | {avail_list_str} |"
        )


        unavail_list_str = (
            "<br>".join(f"`{m}`" for m in unavail_models)
            if unavail_models else "—"
        )
        n_unavail = summary.unavailable
        lines.append(
            f"| 🔴 不可用 | {n_unavail} | {n_unavail / total * 100:.1f}% "
            f"| `{_progress_bar(n_unavail, total)}` | {unavail_list_str} |"
        )

        # 降级可用旁路标记展示
        degraded = (
            ctx.model_availability_check.degraded_models
            if ctx.model_availability_check else {}
        )
        if degraded:
            lines.append("")
            lines.append(
                f"> ⚠️ **降级可用模型**（{len(degraded)} 个）："
                f"平台标记为 degraded，但实测通过，建议监控稳定性。"
            )
            lines.append(
                "> " + "、".join(f"`{m}`" for m in sorted(degraded))
            )

        return "\n".join(lines)

    # ──────────────────────────────────────────────────────────────────
    # 三、推荐模型
    # ──────────────────────────────────────────────────────────────────

    def _recommend_models(self, ctx: ProbeContext) -> str:
        lines = ["## 三、推荐模型", ""]

        matrix = _build_matrix(ctx)
        if not matrix:
            lines.append("_无能力数据，跳过推荐_")
            return "\n".join(lines)

        available = set(_available_model_ids(ctx))
        scored = []
        skipped = []

        for model, probe_results in matrix.items():
            if available and model not in available:
                continue
            basic = probe_results.get(ProbeType.BASIC_CHAT.value)
            streaming = probe_results.get(ProbeType.STREAMING.value)
            is_basic_ok = basic and basic.supported
            is_stream_ok = streaming and streaming.supported
            if not (is_basic_ok or is_stream_ok):
                skipped.append(model)
                continue
            supp, high = _score_model(probe_results)
            lat = 1e9
            if is_basic_ok and basic.latency_ms:
                lat = basic.latency_ms
            elif is_stream_ok and streaming.latency_ms:
                lat = streaming.latency_ms
            scored.append((model, supp, high, lat, probe_results))

        if not scored:
            lines.append("_无可推荐模型（无可用模型）_")
            return "\n".join(lines)

        scored.sort(key=lambda r: (-r[1], -r[2], r[3]))

        MEDALS = ["🥇", "🥈", "🥉"]
        lines.append("基于「能力覆盖数 → 高可靠探针数 → 基础对话延迟」综合排序：")
        lines.append("")
        lines.append("| 排名 | 模型 | 支持能力数 | 支持能力详情 | 高可靠 | 基础对话延迟 |")
        lines.append("|:---:|------|:---:|------|:---:|:---:|")
        for idx, (model, supp, high, lat, probe_results) in enumerate(scored[:3]):
            rank = MEDALS[idx]
            lat_str = f"{lat:.0f} ms" if lat < 1e9 else "—"
            
            supp_details = []
            for p in PROBE_ORDER:
                res = probe_results.get(p)
                if res and res.supported:
                    supp_details.append(PROBE_LABEL_CN[p])
            supp_details_str = "、".join(supp_details) if supp_details else "—"

            lines.append(
                f"| {rank} | `{model}` | {supp}/8 | {supp_details_str} | {high} | {lat_str} |"
            )

        if skipped:
            lines.append("")
            lines.append("> 注：以下模型虽在可用列表中，但本轮流式与非流式通道探测均失败，不纳入推荐：")
            for m in skipped:
                lines.append(f"> - `{m}`")

        return "\n".join(lines)

    # ──────────────────────────────────────────────────────────────────
    # 四、可用模型能力矩阵
    # ──────────────────────────────────────────────────────────────────

    def _generate_capability_matrix_section(self, ctx: ProbeContext) -> str:
        lines = ["## 四、可用模型能力矩阵", ""]
        lines.append(
            "> 数据来源：Stage3 能力探测。**本表仅含 Stage2.5 判定可用的模型**。"
            "各能力含义见附录 A.0。"
        )
        lines.append("")

        matrix = _build_matrix(ctx)
        available = set(_available_model_ids(ctx))
        filtered = {m: v for m, v in matrix.items() if not available or m in available}

        if not filtered:
            lines.append("_未执行能力探测_")
            return "\n".join(lines)

        labels = [PROBE_LABEL_CN[p] for p in PROBE_ORDER]
        header = "| 模型 | " + " | ".join(labels) + " | 支持数 |"
        sep = "|------|" + "|".join([":---:"] * len(PROBE_ORDER)) + "|:---:|"
        lines.append(header)
        lines.append(sep)

        sorted_models = sorted(
            filtered.keys(),
            key=lambda m: _score_model(filtered[m]),
            reverse=True,
        )

        for model in sorted_models:
            probe_results = filtered[model]
            supp = sum(
                1 for p in PROBE_ORDER
                if probe_results.get(p) and probe_results[p].supported
            )

            row = [f"`{model}`"]
            for probe in PROBE_ORDER:
                row.append(_symbol(probe_results.get(probe)))
            row.append(f"**{supp}/{len(PROBE_ORDER)}**")
            lines.append("| " + " | ".join(row) + " |")

        # 各能力支持率进度条
        n_models = len(filtered)
        if n_models:
            lines.append("")
            lines.append(f"**各能力支持率**（{n_models} 个可用模型中支持数）")
            lines.append("")
            lines.append("```")
            probe_counts = []
            for probe in PROBE_ORDER:
                count = sum(
                    1 for pr in filtered.values()
                    if pr.get(probe) and pr[probe].supported
                )
                probe_counts.append((PROBE_LABEL_CN[probe], count))
            probe_counts.sort(key=lambda x: -x[1])
            max_dw = max(_display_width(lbl) for lbl, _ in probe_counts)
            for label, count in probe_counts:
                pad = " " * (max_dw - _display_width(label))
                bar = _progress_bar(count, n_models)
                pct = count / n_models * 100
                lines.append(
                    f"{label}{pad}  {bar}  {count}/{n_models}  {pct:5.1f}%"
                )
            lines.append("```")

        return "\n".join(lines)

    # ──────────────────────────────────────────────────────────────────
    # 五、可用模型问题统计
    # ──────────────────────────────────────────────────────────────────

    def _generate_available_model_issues_section(self, ctx: ProbeContext) -> str:
        lines = ["## 五、可用模型问题统计", ""]
        lines.append(
            "> 数据来源：Stage3 能力探测，**仅针对可用模型**——按能力分组，展示各能力下的失败分布。"
        )
        lines.append("")

        if not ctx.capabilities:
            lines.append("_无错误数据_")
            return "\n".join(lines)

        available = set(_available_model_ids(ctx))

        # 第一层：按能力探针分组
        # probe → (reason, cat, expr, error_text) → list[model_id]
        probe_buckets: dict[str, dict[tuple[str, str, str, str], list[str]]] = {}

        for key, result in ctx.capabilities.items():
            if result.supported is not False:
                continue
            parts = key.split(":", 1)
            if len(parts) != 2:
                continue
            model, probe = parts
            if available and model not in available:
                continue

            # 获取原始大类与小类
            cat = result.error_category or ErrorCategory.UNKNOWN.value
            reason = result.unavailable_reason or UnavailableReason.UNKNOWN.value
            
            # 若仍归为未知，根据错误详情做后置智能推导，消除未知大类/小类
            if cat == ErrorCategory.UNKNOWN.value or reason == UnavailableReason.UNKNOWN.value:
                detail_str = (result.detail or "").lower()
                if "解析" in (result.detail or "") or "expecting" in detail_str or "json" in detail_str:
                    cat = ErrorCategory.MALFORMED_RESPONSE.value
                    reason = UnavailableReason.RESPONSE_INVALID.value
                elif "未调用" in (result.detail or "") or "no choices" in detail_str or "没有 choices" in (result.detail or ""):
                    cat = ErrorCategory.MALFORMED_RESPONSE.value
                    reason = UnavailableReason.RESPONSE_INVALID.value
                elif "语义" in (result.detail or "") or "coherence" in detail_str:
                    cat = ErrorCategory.INCOHERENT_RESPONSE.value
                    reason = UnavailableReason.RESPONSE_INCOHERENT.value

            error_text = _build_probe_error_text(result)
            # 只跳过完全无信息的条目
            if not error_text and cat == ErrorCategory.UNKNOWN.value:
                continue

            # 提取易读的简短出错表现
            detail_msg = result.detail or ""
            if "未调用工具" in detail_msg:
                expr = "未调用工具"
            elif "没有 choices" in detail_msg or "没有choices" in detail_msg or "no choices" in detail_msg.lower():
                expr = "响应缺少 choices 字段"
            elif "解析失败" in detail_msg:
                expr = "响应解析失败"
            elif "响应不是有效 JSON" in detail_msg:
                expr = "响应格式非合法 JSON"
            else:
                cat_meta_temp = ERROR_CATEGORY_META.get(cat, (cat, "—", "—", "—"))
                expr = cat_meta_temp[1] if cat_meta_temp[1] != "—" else "出错表现异常"

            probe_buckets.setdefault(probe, {}).setdefault((reason, cat, expr, error_text), []).append(model)

        if not probe_buckets:
            lines.append("_无失败用例_")
            return "\n".join(lines)

        # 按固定探针顺序输出，仅输出有失败的探针
        for probe in PROBE_ORDER:
            if probe not in probe_buckets:
                continue
            probe_label = PROBE_LABEL_CN.get(probe, probe)
            lines.append(f"### {probe_label}")
            lines.append("")
            lines.append(
                "| 不可用原因 | 错误类型 | 出错表现 | 平台原始响应/详情 | 问题成因 | 影响模型数 | 受影响模型 | 处理建议 |"
            )
            lines.append("|------|------|------|------|------|:---:|------|------|")

            sorted_buckets = sorted(probe_buckets[probe].items(), key=lambda kv: -len(kv[1]))
            for (reason, cat, expr, error_text), affected_models in sorted_buckets:
                reason_label = UNAVAILABLE_REASON_META.get(reason, (reason, "", "", ""))[0]
                cat_meta = ERROR_CATEGORY_META.get(cat, (cat, "—", "—", "—"))
                cat_label, _, cause, suggestion = cat_meta
                
                models_str = "<br>".join(f"`{m}`" for m in sorted(affected_models))
                lines.append(
                    f"| {reason_label} | {cat_label} | {expr} | {error_text} | {cause} "
                    f"| {len(affected_models)} | {models_str} | {suggestion} |"
                )
            lines.append("")

        lines.append("> HTTP 列语义见附录 A.3 末尾。")
        return "\n".join(lines)

    # ──────────────────────────────────────────────────────────────────
    # 六、不可用模型分析
    # ──────────────────────────────────────────────────────────────────

    def _generate_unavailable_model_analysis(self, ctx: ProbeContext) -> str:
        lines = ["## 六、不可用模型分析", ""]
        lines.append(
            "> 数据来源：Stage2.5 可用性预检。逐个列出**基础对话级不可用**"
            "（连基础对话都跑不通）的模型及成因。"
        )
        lines.append("")

        if not ctx.model_availability_check:
            lines.append("_未执行 Stage2.5 可用性预检_")
            return "\n".join(lines)

        unavail = ctx.model_availability_check.unavailable_models
        if not unavail:
            lines.append("_无不可用模型_")
            return "\n".join(lines)

        lines.append(f"共 **{len(unavail)}** 个模型不可用：")
        lines.append("")
        lines.append("| 模型 | 状态 | 成因 | HTTP | 错误摘要 | 成因说明 | 建议 |")
        lines.append("|------|:---:|------|:---:|------|------|------|")

        for model, info in unavail.items():
            reason = info.get("reason", UnavailableReason.UNKNOWN.value)
            meta = UNAVAILABLE_REASON_META.get(
                reason, (reason, "低", "暂未归类", "联系平台支持")
            )
            label, _, cause_desc, suggestion = meta
            status_code = info.get("status_code")
            http_str = str(status_code) if status_code is not None else "—"
            error = (info.get("error") or "").replace("\n", " ").strip()
            # HTML 页面响应（如 502 返回 nginx 错误页）替换为简短描述，避免 < > 破坏表格渲染
            if error.lstrip().startswith("<!") or error.lstrip().startswith("<html"):
                error = "[HTML 页面响应]"
            else:
                # 转义残留的 HTML 特殊字符
                error = error.replace("<", "&lt;").replace(">", "&gt;")
            if len(error) > 60:
                error = error[:57] + "…"
            error_summary = f"`{error}`" if error else "—"
            lines.append(
                f"| `{model}` | 🔴 | {label} | {http_str} "
                f"| {error_summary} | {cause_desc} | {suggestion} |"
            )

        # 成因小结
        lines.append("")
        reason_groups: dict[str, list[str]] = {}
        for model, info in unavail.items():
            r = info.get("reason", UnavailableReason.UNKNOWN.value)
            reason_groups.setdefault(r, []).append(model)

        if len(reason_groups) == 1:
            reason = list(reason_groups.keys())[0]
            label = UNAVAILABLE_REASON_META.get(reason, (reason, "", "", ""))[0]
            n = len(unavail)
            lines.append(
                f"**成因小结**：{n} 个不可用模型均为**{label}**，集中在同一类。"
            )
        else:
            parts = [
                f"{len(ms)} 个{UNAVAILABLE_REASON_META.get(r, (r,))[0]}"
                for r, ms in reason_groups.items()
            ]
            lines.append(f"**成因小结**：{'、'.join(parts)}。")

        return "\n".join(lines)

    # ──────────────────────────────────────────────────────────────────
    # 七、边界探测 / 八、稳定性分析 / 九、阶段失败记录
    # ──────────────────────────────────────────────────────────────────

    def _generate_limits_section(self, ctx: ProbeContext) -> str:
        lines = ["## 七、边界探测", ""]
        if not ctx.limits or not ctx.limits.per_model:
            lines.append("_未执行 Stage4 边界探测_")
            return "\n".join(lines)

        lines.append(
            "> 探测方法：max_tokens 从大到小试至报错取最大成功值；"
            "上下文长度填充 prompt 从小到大试至 400 错误；"
            "速率限制通过「标准响应头 -> 账户端点盲扫 -> 运行期被动 429 反推 -> 阶梯温和并发压测」多级自适应链路获取。"
        )
        lines.append("")
        lines.append("| 模型 | 最大输出 token | 最大上下文长度 | 速率限制 (RPM) | 速率获取来源 |")
        lines.append("|------|:---:|:---:|:---:|:---:|")
        for model, lim in ctx.limits.per_model.items():
            if isinstance(lim.max_tokens, int):
                mt = f"{lim.max_tokens:,}"
            elif lim.max_tokens:
                mt = f"_{lim.max_tokens}_"
            else:
                mt = "_未探测_"

            if isinstance(lim.max_context_length, int):
                mc = f"{lim.max_context_length:,}"
            elif lim.max_context_length:
                mc = f"_{lim.max_context_length}_"
            else:
                mc = "_未探测_"

            rpm = f"{lim.rate_limit_rpm:,}" if lim.rate_limit_rpm else "_未获取_"
            
            # 获取来源并添加 Emoji
            source = getattr(lim, "rate_limit_source", None)
            if source == "Header 提取":
                source_str = "Header 提取 🏷️"
            elif source == "端点盲扫":
                source_str = "账户端点盲扫 🔍"
            elif source == "429 反推":
                source_str = "历史 429 反推 ⏳"
            elif source == "压测判定":
                source_str = "压测判定 📊"
            else:
                source_str = "—" if lim.rate_limit_rpm else "_未获取_"
                
            lines.append(f"| `{model}` | {mt} | {mc} | {rpm} | {source_str} |")
        return "\n".join(lines)

    def _generate_stability_section(self, ctx: ProbeContext) -> str:
        lines = ["## 八、稳定性分析", ""]
        if not ctx.stability or not ctx.stability.per_model:
            lines.append("_未执行 Stage5 稳定性分析_")
            return "\n".join(lines)

        stab = ctx.stability
        p_stars = "★" * stab.platform_star_rating + "☆" * (5 - stab.platform_star_rating)
        lines.append(
            f"> 平台整体：成功率 **{stab.platform_success_rate:.1%}**，"
            f"综合评级 {p_stars}（{stab.platform_star_rating}/5）"
        )
        lines.append(f"> 每模型各发送 5 次基础对话请求。")
        lines.append("")
        lines.append("| 模型 | 成功率 | 平均延迟 | 星级 | 错误模式 |")
        lines.append("|------|:---:|:---:|:---:|------|")
        for model, ms in stab.per_model.items():
            m_stars = "★" * ms.star_rating + "☆" * (5 - ms.star_rating)
            lat_str = f"{ms.avg_latency_ms:.0f} ms" if ms.avg_latency_ms else "—"
            err_str = (
                "、".join(f"`{p}`" for p in ms.error_patterns)
                if ms.error_patterns else "—"
            )
            lines.append(
                f"| `{model}` | {ms.success_rate:.1%} | {lat_str} | {m_stars} | {err_str} |"
            )
        return "\n".join(lines)

    def _generate_failures_section(self, ctx: ProbeContext) -> str:
        section = "## 九、阶段失败记录"
        if not ctx.failures:
            return f"{section}\n\n> 仅当存在阶段级异常时显示。本次探测无阶段失败。"
        lines = [
            section, "",
            "| 阶段 | 错误类型 | 错误信息 |",
            "|:---:|------|------|",
        ]
        for f in ctx.failures:
            msg = f.error_message.replace("\n", " ").strip()
            if len(msg) > 200:
                msg = msg[:200] + "…"
            lines.append(f"| Stage{f.stage} | {f.error_type} | {msg} |")
        return "\n".join(lines)

    # ──────────────────────────────────────────────────────────────────
    # 附录 A
    # ──────────────────────────────────────────────────────────────────

    def _generate_appendix(self) -> str:
        fast_s = self.timeouts.fast_threshold_ms / 1000
        slow_s = self.timeouts.slow_threshold_ms / 1000

        lines = [
            "---",
            "",
            "## 附录 A：状态符号说明",
            "",
            "### A.0 八项能力说明",
            "",
            "| 能力 | 探针 | 检验内容 |",
            "|------|------|------|",
            "| 基础对话 | basic_chat | 单轮问答能否正常返回 |",
            "| 流式 | streaming | SSE 流式输出是否支持 |",
            "| 工具调用 | tool_calling | function calling / tools 参数 |",
            "| 视觉 | vision | 图片输入（image_url / base64） |",
            "| JSON | json_mode | 结构化 JSON 输出 |",
            "| 推理 | reasoning | 推理 / 思维链能力 |",
            "| 联网 | web_search | 联网搜索能力 |",
            "| 多轮 | multi_turn | 多轮对话上下文记忆（能否记住前几轮内容） |",
            "",
            "### A.1 响应健康度",
            "",
            "| 状态 | 阈值 | 含义 | 建议 |",
            "|------|------|------|------|",
            f"| 🟢 健康 | 首字节 < {fast_s:.0f}s | 模型快速响应 | 推荐 |",
            f"| 🟡 半死不活 | {fast_s:.0f}s ~ {slow_s:.0f}s | 后端排队/慢 | 仅离线/异步场景 |",
            f"| 🔴 不响应 | > {slow_s:.0f}s 或异常 | 后端死锁或上游断连 | 避免使用 |",
            "",
            "### A.2 能力矩阵符号",
            "",
            "| 符号 | 含义 |",
            "|:---:|------|",
            "| ✓ | 支持且首字节健康（<30s） |",
            "| 🟡 | 支持但响应缓慢（30~60s 或流式 fallback） |",
            "| ⚠ | 支持但格式/质量有瑕疵 |",
            "| ? | 支持但可靠性低（语义可疑） |",
            "| ✗ | 不支持 / 探测失败 |",
            "| N/A | 未测试 |",
            "",

            "### A.3 错误分类（13 类 ErrorCategory）",
            "",
            "| 分类 | 表现 | 根因 | 处理建议 |",
            "|------|------|------|------|",
        ]
        for label, expression, cause, action in ERROR_CATEGORY_META.values():
            lines.append(f"| {label} | {expression} | {cause} | {action} |")

        lines += [
            "",
            "**HTTP 状态码语义**（第五/六章「HTTP」列含义）：",
            "",
            "| HTTP | 含义 |",
            "|:---:|------|",
            "| 200 | 请求成功但响应内容异常（空 body / 解析失败） |",
            "| 400 | 请求被拒（参数不被接受，如视觉模型拒收 `image_url`） |",
            "| 401 / 403 / 404 / 429 / 402 | 认证/权限/不存在/限流/付费，见上方分类表 |",
            "| — | 未发出 HTTP 请求（网络层错误，如超时、断连） |",
            "",
            f"> 响应阈值可通过 `ProbeTimeouts` 配置调整"
            f"（当前：fast={fast_s:.0f}s, slow={slow_s:.0f}s）。",
        ]
        return "\n".join(lines)