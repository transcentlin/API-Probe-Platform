# 修改历史 (Revision History)
# ==================================
# 版本: v1.0.0
# 日期: 2026-06-15
# 修改说明: 实现 Markdown 报告文本提取器，支持对基本指标、可达延迟、推荐模型及能力矩阵的结构化数据提取。
# ==================================

# -*- coding: utf-8 -*-
import os
import re
from pathlib import Path
from typing import Optional, Any

class ReportParser:
    """探测报告 Markdown 解析器。"""

    @staticmethod
    def parse_file(file_path: Path) -> dict[str, Any]:
        """解析 Markdown 报告文件，返回结构化数据。"""
        if not file_path.exists():
            return {}

        content = file_path.read_text(encoding="utf-8")
        lines = content.splitlines()

        result = {
            "platform_name": "Unknown",
            "health_level": "未知",
            "availability_rate": 0.0,
            "available_count": 0,
            "total_count": 0,
            "latency_ms": None,
            "recommended_model": "",
            "recommended_latency_ms": None,
            "models_matrix": []
        }

        # 1. 尝试从文件名提取默认平台名称
        # 例如: CF_WorkerAI_探测报告_260615_2205.md
        match_fn = re.match(r"^(.+?)_探测报告_", file_path.name)
        if match_fn:
            result["platform_name"] = match_fn.group(1)

        # 2. 解析健康度和可用率 (执行摘要)
        # 寻找包含执行摘要表格的数据行
        # | 平台健康度 | 模型可用率 | 可用 / 总数 | 推荐首选 |
        # | :---: | :---: | :---: | :---: |
        # | 🔴 **差** | **37.3%** | 22 / 59 | `@cf/meta/llama-3.2-3b-instruct` |
        summary_table_idx = -1
        for i, line in enumerate(lines):
            if "平台健康度" in line and "模型可用率" in line:
                summary_table_idx = i
                break

        if summary_table_idx != -1 and summary_table_idx + 2 < len(lines):
            data_line = lines[summary_table_idx + 2]
            parts = [p.strip() for p in data_line.split("|") if p.strip()]
            if len(parts) >= 3:
                # 提取健康等级
                raw_health = parts[0]
                # 清除 Emoji 和 ** 标记
                raw_health = re.sub(r"[^\u4e00-\u9fa5a-zA-Z0-9]", "", raw_health)
                result["health_level"] = raw_health

                # 提取可用率
                raw_rate = parts[1]
                rate_match = re.search(r"([\d\.]+)%", raw_rate)
                if rate_match:
                    result["availability_rate"] = float(rate_match.group(1))

                # 提取可用 / 总数
                raw_counts = parts[2]
                counts_match = re.search(r"(\d+)\s*/\s*(\d+)", raw_counts)
                if counts_match:
                    result["available_count"] = int(counts_match.group(1))
                    result["total_count"] = int(counts_match.group(2))

                # 推荐首选
                if len(parts) >= 4:
                    raw_rec = parts[3]
                    raw_rec = raw_rec.replace("`", "").strip()
                    if raw_rec and raw_rec != "—":
                        result["recommended_model"] = raw_rec

        # 3. 解析连通性延迟 (一、平台概览)
        # | 可达性 | ✅ 可达（1130 ms） |
        for line in lines:
            if "可达性" in line and "ms" in line:
                lat_match = re.search(r"（(\d+)\s*ms）|\((\d+)\s*ms\)", line)
                if lat_match:
                    val = lat_match.group(1) or lat_match.group(2)
                    result["latency_ms"] = int(val)
                break

        # 4. 解析推荐首选模型时延 (三、推荐模型)
        # | 🥇 | `@cf/meta/...` | 6/8 | ... | 5 | 3732 ms |
        rec_table_idx = -1
        for i, line in enumerate(lines):
            if "三、推荐模型" in line:
                rec_table_idx = i
                break

        if rec_table_idx != -1:
            for i in range(rec_table_idx + 1, min(rec_table_idx + 20, len(lines))):
                line = lines[i]
                if "🥇" in line and "ms" in line:
                    lat_match = re.search(r"(\d+)\s*ms", line)
                    if lat_match:
                        result["recommended_latency_ms"] = int(lat_match.group(1))
                    break

        # 5. 解析能力矩阵 (四、可用模型能力矩阵)
        # | 模型 | 流式 | 非流式 | 工具调用 | 视觉 | JSON | 推理 | 联网 | 多轮 | 支持数 |
        matrix_start_idx = -1
        for i, line in enumerate(lines):
            if "四、可用模型能力矩阵" in line:
                matrix_start_idx = i
                break

        if matrix_start_idx != -1:
            # 找到表头所在行
            header_idx = -1
            for j in range(matrix_start_idx + 1, min(matrix_start_idx + 10, len(lines))):
                if "模型" in lines[j] and "流式" in lines[j]:
                    header_idx = j
                    break

            if header_idx != -1:
                # 遍历数据行，数据行以下一个二级标题、空行或分割线结束
                for k in range(header_idx + 2, len(lines)):
                    line = lines[k].strip()
                    if not line or line.startswith("#") or line.startswith("---") or "数据来源" in line:
                        if len(result["models_matrix"]) > 0:
                            # 已经读取到矩阵且遇到分割了，退出
                            break
                        continue

                    if line.startswith("|"):
                        parts = [p.strip() for p in line.split("|")]
                        # 去掉首尾空元素
                        if parts and not parts[0]:
                            parts.pop(0)
                        if parts and not parts[-1]:
                            parts.pop()

                        if len(parts) >= 10:
                            model_name = parts[0].replace("`", "").strip()
                            if model_name == "模型" or parts[1].startswith(":---"):
                                continue

                            # 提取 8 项能力指标（✓ / ✗ / 🟡 / ⚠ / ?）
                            caps = []
                            for p in parts[1:9]:
                                val = p.strip()
                                if val in ("✓", "✓"):
                                    caps.append(1.0)
                                elif val in ("🟡", "⚠", "?"):
                                    caps.append(0.5)
                                else:
                                    caps.append(0.0)

                            result["models_matrix"].append({
                                "model_name": model_name,
                                "streaming": caps[0] == 1.0,
                                "non_streaming": caps[1] == 1.0,
                                "advanced_caps": caps[2:]  # 6 项高级能力得分
                            })

        return result
