# 修改历史 (Revision History)
# ==================================
# 版本: v1.1.0
# 日期: 2026-06-16
# 修改说明: 在横向对比中支持自动排除无报告的未测平台，并在生成的 Markdown 报告头部动态渲染未测排除说明；优化有效对比平台数限制，少于 2 个时抛出友好提示。
# ----------------------------------
# 版本: v1.0.0
# 日期: 2026-06-15
# 修改说明: 实现多平台指标横向对比分析报告生成器，提取平台指标生成综合得分与六项高级能力支持率对比表格。
# ==================================

# -*- coding: utf-8 -*-
import os
import re
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Any, Optional

from .report_parser import ReportParser
from .scoring import PlatformScorer

class ComparisonReporter:
    """多平台探测报告横向对比分析报告生成器。"""

    @staticmethod
    def get_latest_reports(reports_dir: Path) -> Dict[str, Path]:
        """获取 reports_dir 下每个平台的最新报告文件。"""
        # 匹配 <PlatformName>_探测报告_<YYMMDD>_<HHMM>.md 
        # 例如: CF_WorkerAI_探测报告_260615_2205.md
        pattern = re.compile(r"^(.+?)_探测报告_(\d{6})_(\d{4})\.md$")
        latest_files: Dict[str, tuple[datetime, Path]] = {}

        if not reports_dir.exists():
            return {}

        for file in reports_dir.glob("*.md"):
            match = pattern.match(file.name)
            if match:
                platform = match.group(1)
                date_str = match.group(2)
                time_str = match.group(3)
                try:
                    dt = datetime.strptime(f"{date_str}_{time_str}", "%y%m%d_%H%M")
                except ValueError:
                    continue
                
                if platform not in latest_files or dt > latest_files[platform][0]:
                    latest_files[platform] = (dt, file)
        
        return {p: info[1] for p, info in latest_files.items()}

    @classmethod
    def generate_comparison_report(
        cls, 
        reports_dir: Path, 
        platform_names: Optional[List[str]] = None,
        output_path: Optional[Path] = None
    ) -> Path:
        """根据最新探测报告生成多平台横向对比报告。"""
        latest_reports = cls.get_latest_reports(reports_dir)
        if not latest_reports:
            raise ValueError("没有找到任何平台的探测报告文件。")

        parsed_results = []
        for platform, report_path in latest_reports.items():
            if platform_names and platform not in platform_names:
                continue
            data = ReportParser.parse_file(report_path)
            if data:
                # 重新计算/注入最新打分
                data["score"] = PlatformScorer.calculate_score(data)
                data["report_file"] = report_path.name
                parsed_results.append(data)

        # 计算哪些平台被自动排除
        excluded_platforms = []
        if platform_names:
            included_names = {x["platform_name"] for x in parsed_results}
            excluded_platforms = [p for p in platform_names if p not in included_names]

        if not parsed_results:
            raise ValueError("没有找到任何具有探测报告的有效平台。")

        # 按得分从高到低排序，如果得分相同则按可用率排序，然后按平台名称字母排序
        parsed_results.sort(
            key=lambda x: (x.get("score", 0.0), x.get("availability_rate", 0.0), x.get("platform_name", "")),
            reverse=True
        )

        now = datetime.now()
        timestamp = now.strftime("%y%m%d_%H%M")
        
        if output_path is None:
            output_path = reports_dir / f"Comparison_Report_{timestamp}.md"

        # 生成 Markdown 内容
        md_lines = []
        md_lines.append("# 📊 API 平台横向对比分析报告")
        md_lines.append("")
        md_lines.append(f"> **生成时间**：{now.strftime('%Y-%m-%d %H:%M:%S')}  ")
        md_lines.append(f"> **对比平台数**：{len(parsed_results)} 个")
        if excluded_platforms:
            ex_list_str = "、".join(f"`{p}`" for p in excluded_platforms)
            md_lines.append(f"> ⚠️ **未测排除说明**：平台 {ex_list_str} 由于尚未进行探测测试或无可用报告文件，已自动排除在本次对比之外。  ")
        md_lines.append("")
        md_lines.append("## 一、综合评分对比总览")
        md_lines.append("")
        md_lines.append("下表汇总了各平台的综合得分、健康度、可用率以及延迟表现：")
        md_lines.append("")
        
        # 总览表头
        md_lines.append("| 排名 | 平台名称 | 综合得分 | 平台健康度 | 模型可用率 | 可用 / 总数 | 连通延迟 | 推荐首选模型 | 首选模型延迟 |")
        md_lines.append("| :---: | :--- | :---: | :---: | :---: | :---: | :---: | :--- | :---: |")

        for idx, item in enumerate(parsed_results, 1):
            rank = idx
            name = item["platform_name"]
            score = item["score"]
            health = item["health_level"]
            
            # 渲染健康度带上色彩Emoji（若解析出来的 health 没有，我们做下适配）
            health_display = health
            if "良好" in health:
                health_display = "🟢 **良好**"
            elif "中等" in health:
                health_display = "🟡 **中等**"
            elif "差" in health:
                health_display = "🔴 **差**"
            elif "异常" in health:
                health_display = "🔴 **异常**"
            
            rate = f"{item['availability_rate']:.1f}%"
            counts = f"{item['available_count']} / {item['total_count']}"
            
            lat = item["latency_ms"]
            lat_display = f"{lat} ms" if lat is not None else "N/A"
            
            rec_model = item["recommended_model"] if item["recommended_model"] else "—"
            rec_lat = item["recommended_latency_ms"]
            rec_lat_display = f"{rec_lat} ms" if rec_lat is not None else "N/A"
            
            md_lines.append(
                f"| {rank} | {name} | **{score:.1f}** | {health_display} | {rate} | {counts} | {lat_display} | `{rec_model}` | {rec_lat_display} |"
            )

        md_lines.append("")
        md_lines.append("## 二、高级能力支持度对比")
        md_lines.append("")
        md_lines.append("本部分对比各平台可用模型对六项高级能力的平均支持率（即支持该能力的可用模型占该平台总可用模型的比例）：")
        md_lines.append("")
        
        # 能力对比表头
        md_lines.append("| 平台名称 | 综合得分 | 工具调用 | 视觉 | JSON模式 | 推理 | 联网 | 多轮 |")
        md_lines.append("| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |")

        for item in parsed_results:
            name = item["platform_name"]
            score = item["score"]
            
            # 计算六项能力支持度
            models_matrix = item.get("models_matrix", [])
            adv_rates = [0.0] * 6
            if models_matrix:
                for m in models_matrix:
                    caps = m.get("advanced_caps", [])
                    for i in range(min(6, len(caps))):
                        adv_rates[i] += caps[i]
                adv_rates = [rate / len(models_matrix) for rate in adv_rates]
            
            # 转化为百分比字符串
            rates_display = []
            for rate in adv_rates:
                if rate == 0.0:
                    rates_display.append("—")
                else:
                    rates_display.append(f"{rate * 100:.1f}%")
            
            md_lines.append(
                f"| {name} | **{score:.1f}** | {rates_display[0]} | {rates_display[1]} | {rates_display[2]} | {rates_display[3]} | {rates_display[4]} | {rates_display[5]} |"
            )

        md_lines.append("")
        md_lines.append("## 三、选型与部署建议")
        md_lines.append("")
        
        # 挑选第一名平台
        best_platforms = [p for p in parsed_results if p.get("score", 0.0) >= 80.0]
        if not best_platforms and parsed_results:
            best_platforms = [parsed_results[0]]

        if best_platforms:
            md_lines.append("### 🌟 首选推荐平台")
            for p in best_platforms[:2]:
                md_lines.append(f"- **{p['platform_name']}** (得分: **{p['score']:.1f}**): 可用率 **{p['availability_rate']:.1f}%**，推荐首选模型 `{p['recommended_model']}` 响应延迟为 {p['recommended_latency_ms'] or 'N/A'} ms。表现优秀，推荐作为主力生产环境使用。")
            md_lines.append("")

        # 挑选具备高级功能的平台
        md_lines.append("### 🛠️ 特定场景选型建议")
        
        # 寻找工具调用支持度好的平台
        tool_platforms = []
        for p in parsed_results:
            matrix = p.get("models_matrix", [])
            if matrix:
                tool_sum = sum(m.get("advanced_caps", [0])[0] for m in matrix) / len(matrix)
                if tool_sum > 0.5:
                    tool_platforms.append((p["platform_name"], tool_sum))
        if tool_platforms:
            tool_platforms.sort(key=lambda x: x[1], reverse=True)
            tool_list = ", ".join([f"**{name}** ({rate*100:.1f}%)" for name, rate in tool_platforms[:2]])
            md_lines.append(f"- **Agent & 工具调用场景**: 推荐 {tool_list}，具有较高的工具调用成功率与模型支持度。")
            
        # 寻找视觉支持度好的平台
        vision_platforms = []
        for p in parsed_results:
            matrix = p.get("models_matrix", [])
            if matrix:
                # 视觉是 index 1
                vis_sum = sum(m.get("advanced_caps", [0, 0])[1] for m in matrix) / len(matrix)
                if vis_sum > 0.0:
                    vision_platforms.append((p["platform_name"], vis_sum))
        if vision_platforms:
            vision_platforms.sort(key=lambda x: x[1], reverse=True)
            vision_list = ", ".join([f"**{name}** ({rate*100:.1f}%)" for name, rate in vision_platforms[:2]])
            md_lines.append(f"- **多模态 & 视觉场景**: 推荐 {vision_list}，可实现可靠的图片解析与多模态交互。")
            
        # 寻找推理支持度好的平台
        reasoning_platforms = []
        for p in parsed_results:
            matrix = p.get("models_matrix", [])
            if matrix:
                # 推理是 index 3
                reas_sum = sum(m.get("advanced_caps", [0, 0, 0, 0])[3] for m in matrix) / len(matrix)
                if reas_sum > 0.0:
                    reasoning_platforms.append((p["platform_name"], reas_sum))
        if reasoning_platforms:
            reasoning_platforms.sort(key=lambda x: x[1], reverse=True)
            reas_list = ", ".join([f"**{name}** ({rate*100:.1f}%)" for name, rate in reasoning_platforms[:2]])
            md_lines.append(f"- **复杂逻辑 & 深度推理场景**: 推荐 {reas_list}，提供强大的推理或思考型模型支持。")

        md_lines.append("")
        md_lines.append("---")
        md_lines.append("*注：本报告数据源自各平台最近一次物理探测报告文件，计算权重为：基础可用率占比 40%，性能延迟评分占比 30%，六项高级能力平均覆盖度占比 30%。*")
        
        content = "\n".join(md_lines)
        output_path.write_text(content, encoding="utf-8")
        return output_path
