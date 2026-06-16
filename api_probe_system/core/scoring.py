# 修改历史 (Revision History)
# ==================================
# 版本: v1.0.1
# 日期: 2026-06-16
# 修改说明: 新增静态方法 calculate_score_from_ctx 以支持从 ProbeContext 动态解析指标并计算百分制综合得分。
# ==================================

# -*- coding: utf-8 -*-
from typing import Any

class PlatformScorer:
    """平台质量打分引擎。"""

    @staticmethod
    def calculate_score(parsed_data: dict[str, Any]) -> float:
        """根据 ReportParser 解析的结构化指标，计算平台的 0~100 综合得分。"""
        # 前置熔断逻辑：若平台不可达或可用模型数为 0，直接判定为 0 分
        if parsed_data.get("latency_ms") is None:
            return 0.0
        if parsed_data.get("available_count", 0) <= 0:
            return 0.0

        # 1. 基础分 (40%) = 可用率 * 100
        availability_rate = parsed_data.get("availability_rate", 0.0)
        base_score = availability_rate

        # 2. 性能分 (30%) = 推荐首选模型对话延迟评分
        # T (ms) = recommended_latency_ms
        recommended_latency = parsed_data.get("recommended_latency_ms")
        perf_score = 0.0
        if recommended_latency is not None:
            t = float(recommended_latency)
            if t <= 1000.0:
                perf_score = 100.0
            elif 1000.0 < t <= 3000.0:
                # 1s ~ 3s 范围内平滑降级扣分，从 90分 到 40分
                perf_score = 90.0 - (t - 1000.0) / 100.0 * 2.5
            elif 3000.0 < t <= 10000.0:
                perf_score = 40.0
            else:
                perf_score = 0.0
        else:
            # 如果没有时延，且可用模型数大于0，说明测试中发生严重异常导致无时延，记0分
            perf_score = 0.0

        # 3. 功能分 (30%) = 可用模型高级能力(6项)支持率平均分
        # 高级能力：工具调用、视觉、JSON、推理、联网、多轮 (matrix 中的 advanced_caps)
        models_matrix = parsed_data.get("models_matrix", [])
        func_score = 0.0
        if models_matrix:
            total_adv_score = 0.0
            for model in models_matrix:
                adv_caps = model.get("advanced_caps", [])
                if len(adv_caps) > 0:
                    # 计算该模型的高级能力平均分，Caps 为分数列表
                    model_adv_score = sum(adv_caps) / len(adv_caps) * 100.0
                    total_adv_score += model_adv_score
            # 取所有可用模型的平均值
            func_score = total_adv_score / len(models_matrix)

        # 4. 汇总总分
        final_score = (base_score * 0.40) + (perf_score * 0.30) + (func_score * 0.30)
        
        # 确保得分在 0 ~ 100 范围内，并保留一位小数
        return round(max(0.0, min(100.0, final_score)), 1)

    @staticmethod
    def calculate_score_from_ctx(ctx: "ProbeContext") -> float:
        """从 ProbeContext 中动态提取核心指标，并利用统一打分算法计算 0~100 综合得分。"""
        from .analyzer import ResultAnalyzer
        from .constants import ProbeType
        from .models import ProbeContext
        
        # 1. 连通性熔断判定
        reachable = ctx.connectivity.reachable if ctx.connectivity else True
        if not reachable:
            return 0.0
            
        summary = ResultAnalyzer().analyze_model_availability(ctx)
        if summary.total_models <= 0 or summary.fully_available <= 0:
            return 0.0
            
        # 2. 构造 parsed_data 结构体
        # 提取 recommended_latency_ms
        matrix = {}
        for key, result in ctx.capabilities.items():
            if ":" not in key:
                continue
            model, probe_name = key.split(":", 1)
            matrix.setdefault(model, {})[probe_name] = result
            
        available = set(ctx.model_availability_check.available_models) if ctx.model_availability_check else set()
        if not available:
            # 回退
            available = {
                key.split(":", 1)[0]
                for key, r in ctx.capabilities.items()
                if key.endswith(f":{ProbeType.BASIC_CHAT.value}") and r.supported
            }
            
        scored = []
        for model, probe_results in matrix.items():
            if available and model not in available:
                continue
            basic = probe_results.get(ProbeType.BASIC_CHAT.value)
            if not (basic and basic.supported):
                continue
            # 支持数
            supp = sum(1 for r in probe_results.values() if r and r.supported)
            # 高可靠
            high = sum(1 for r in probe_results.values() if r and r.supported and r.reliability == "high")
            lat = basic.latency_ms if basic.latency_ms else 1e9
            scored.append((model, supp, high, lat))
            
        recommended_latency_ms = None
        if scored:
            scored.sort(key=lambda r: (-r[1], -r[2], r[3]))
            top_model = scored[0][0]
            top_probes = matrix.get(top_model, {})
            basic = top_probes.get(ProbeType.BASIC_CHAT.value)
            if basic and basic.supported and basic.latency_ms:
                recommended_latency_ms = basic.latency_ms
                
        # 3. 构造 models_matrix 用于能力分计算
        models_matrix_data = []
        for model in available:
            probe_results = matrix.get(model, {})
            if not probe_results:
                continue
            
            from .constants import ResponseHealth
            
            # PROBE_ORDER = [流式, 非流式, 其他...]
            streaming_res = probe_results.get(ProbeType.STREAMING.value)
            streaming_ok = streaming_res.supported if (streaming_res and streaming_res.supported is not None) else False
            
            basic_res = probe_results.get(ProbeType.BASIC_CHAT.value)
            non_streaming_ok = basic_res.supported if (basic_res and basic_res.supported is not None) else False
            
            advanced_probes = [
                ProbeType.TOOL_CALLING.value,
                ProbeType.VISION.value,
                ProbeType.JSON_MODE.value,
                ProbeType.REASONING.value,
                ProbeType.WEB_SEARCH.value,
                ProbeType.MULTI_TURN.value,
            ]
            advanced_caps = []
            for p in advanced_probes:
                res = probe_results.get(p)
                if res is None or res.supported is None:
                    advanced_caps.append(0.0)
                elif res.supported:
                    if res.response_health == ResponseHealth.SLUGGISH.value or res.reliability in ("medium", "low"):
                        advanced_caps.append(0.5)
                    else:
                        advanced_caps.append(1.0)
                else:
                    advanced_caps.append(0.0)
                    
            models_matrix_data.append({
                "model_name": model,
                "streaming": streaming_ok,
                "non_streaming": non_streaming_ok,
                "advanced_caps": advanced_caps
            })
            
        parsed_data = {
            "latency_ms": ctx.connectivity.latency_ms if (ctx.connectivity and ctx.connectivity.reachable) else None,
            "available_count": summary.fully_available,
            "total_count": summary.total_models,
            "availability_rate": summary.availability_rate() * 100.0,
            "recommended_latency_ms": recommended_latency_ms,
            "models_matrix": models_matrix_data
        }
        
        return PlatformScorer.calculate_score(parsed_data)

