# 修改历史 (Revision History)
# ==================================
# 版本: v1.2.1
# 日期: 2026-06-16
# 修改说明: 1) 在 list_platforms 端点对 reports 目录进行仅一次的全量扫描，重组为 platform-to-report 映射，实现 O(N) 到 O(1) 磁盘扫描优化；2) 调整 _inject_scoring_info 和 _to_response 接口，支持接收预解析的 latest_report 参数。
# ----------------------------------
# 版本: v1.2.0
# 日期: 2026-06-16
# 修改说明: 在 _get_latest_report_for_platform 中引入精确定向 glob 与纯文件名降序排序优化，并在 _inject_scoring_info 中引入全局 _SCORING_CACHE 内存缓存，彻底解决百度同步盘下大 I/O 阻塞造成的页面卡死 Bug。
# ----------------------------------
# 版本: v1.1.3
# 日期: 2026-06-16
# 修改说明: 新增 GET /warnings 路由，用于读取并返回平台探测阶段中产生的处理器兼容性告警列表。
# ----------------------------------
# 版本: v1.1.2
# 日期: 2026-06-16
# 修改说明: update_platform 路由支持修改平台名称，当名字发生改变时，同步重命名磁盘上相关的物理探测报告文件，并解决重命名后获取平台数据抛出 404 错误的问题。
# ----------------------------------
# 版本: v1.1.1
# 日期: 2026-06-16
# 修改说明: 修改 _inject_scoring_info 以便从物理报告中多提取并返回已测试出的可用模型总数，并装配进 _to_response 平台响应中的 active_models_count 字段。
# ----------------------------------
# 版本: v1.1.0
# 日期: 2026-06-15
# 修改说明: 挂载实时打分与 top 模型数据装配逻辑，在返回平台响应时动态解析报告计算评分和优选模型。
# ----------------------------------
# 版本: v1.0.0
# 日期: 2026-06-15
# 修改说明: 实现平台管理 API 路由，公开 CRUD + Toggle 6 个 REST 接口。
# ==================================

# -*- coding: utf-8 -*-
import re
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional, Any
from fastapi import APIRouter, Depends, HTTPException, status
from api_probe_system.core.platform_manager import PlatformManager, PlatformEntry
from api_probe_system.core.secret import SecretResolver
from api_probe_system.core.report_parser import ReportParser
from api_probe_system.core.scoring import PlatformScorer
from api_probe_system.web.dependencies import get_platform_manager, get_config_manager
from api_probe_system.web.schemas import PlatformCreate, PlatformUpdate, PlatformResponse, PlatformToggle

logger = logging.getLogger("api_probe_system.web.routes.platforms")
router = APIRouter(prefix="/platforms", tags=["Platforms"])

# 内存缓存，防止对未修改的报告文件进行重复 I/O 及解析打分
# 格式为: { platform_name: { "report_filename": str, "score": float, "top_models": list, "total_available": int } }
_SCORING_CACHE: dict[str, dict[str, Any]] = {}

REPORT_PATTERN = re.compile(r"^(.+?)_探测报告_(\d{6}_\d{4})\.md$")

def _get_latest_report_for_platform(platform_name: str, reports_dir: Path) -> Optional[Path]:
    """获取指定平台的最新报告文件。"""
    if not reports_dir.exists():
        return None
    # 针对同步盘优化：精确定向匹配该平台的报告，直接过滤无关平台，且利用文件名降序排序（文件名后缀 yymmdd_HHMM 精准对应时间）
    files = list(reports_dir.glob(f"{platform_name}_探测报告_*.md"))
    if not files:
        return None
    files.sort(key=lambda p: p.name, reverse=True)
    return files[0]

def _inject_scoring_info(
    platform_name: str,
    reports_dir: Path,
    latest_report: Optional[Path] = None
) -> tuple[Optional[float], list[str], int]:
    """解析最新报告并返回评分、前三个可用模型及可用模型总数。"""
    report_path = latest_report if latest_report is not None else _get_latest_report_for_platform(platform_name, reports_dir)
    if not report_path:
        return None, [], 0
    
    filename = report_path.name

    # 检查缓存是否命中
    if platform_name in _SCORING_CACHE:
        cached = _SCORING_CACHE[platform_name]
        if cached.get("report_filename") == filename:
            # 文件名和上次解析一致，直接从内存秒级返回
            return cached["score"], cached["top_models"], cached["total_available"]
    
    try:
        parsed_data = ReportParser.parse_file(report_path)
        if not parsed_data:
            return None, [], 0
        
        score = PlatformScorer.calculate_score(parsed_data)
        
        # 挑选可用模型中排名前三的模型 (top_models)
        models_matrix = parsed_data.get("models_matrix", [])
        
        # 支持数 = (1 if streaming else 0) + (1 if non_streaming else 0) + sum(advanced_caps)
        def get_model_support_count(m: dict[str, Any]) -> float:
            count = 0.0
            if m.get("streaming"):
                count += 1.0
            if m.get("non_streaming"):
                count += 1.0
            count += sum(m.get("advanced_caps", []))
            return count

        # 排序：按支持数降序，再按模型名称升序
        sorted_models = sorted(
            models_matrix,
            key=lambda x: (get_model_support_count(x), x.get("model_name", "")),
            reverse=True
        )
        
        # 只保留前 3 个模型的名称
        top_models = [m["model_name"] for m in sorted_models[:3]]
        total_available = len(models_matrix)

        # 写入缓存
        _SCORING_CACHE[platform_name] = {
            "report_filename": filename,
            "score": score,
            "top_models": top_models,
            "total_available": total_available
        }
        
        return score, top_models, total_available
    except Exception as e:
        logger.error(f"解析报告打分注入失败 ({platform_name}): {e}")
        return None, [], 0

def _to_response(
    entry: PlatformEntry,
    reports_dir: Path,
    latest_report: Optional[Path] = None
) -> PlatformResponse:
    score, top_models, active_models_count = _inject_scoring_info(entry.name, reports_dir, latest_report)
    return PlatformResponse(
        name=entry.name,
        base_url=entry.base_url,
        api_key=SecretResolver.mask(entry.api_key),
        enabled=entry.enabled,
        website=entry.website or "",
        notes=entry.notes or "",
        hints=entry.hints or {},
        discovery_handler=entry.discovery_handler or "openai",
        score=score,
        top_models=top_models,
        active_models_count=active_models_count,
    )

@router.get("", response_model=list[PlatformResponse])
async def list_platforms(
    pm: PlatformManager = Depends(get_platform_manager),
    config_mgr = Depends(get_config_manager)
):
    """获取所有平台列表（API Key 均已脱敏）。"""
    reports_dir = Path(config_mgr.project_root) / "reports"
    
    # 💥 优化：只扫描 reports 目录一次，建立所有平台的最新报告文件映射，防百度同步盘下大 I/O 阻塞
    latest_reports_map = {}
    if reports_dir.exists():
        try:
            # 找到所有的 md 报告文件并按名称降序排序 (时间戳在文件名中自然对齐)
            all_files = list(reports_dir.glob("*_探测报告_*.md"))
            all_files.sort(key=lambda p: p.name, reverse=True)
            for f in all_files:
                match = REPORT_PATTERN.match(f.name)
                if match:
                    plat_name = match.group(1)
                    if plat_name not in latest_reports_map:
                        latest_reports_map[plat_name] = f
        except Exception as e:
            logger.error(f"预扫描报告目录失败: {e}")
            
    return [_to_response(p, reports_dir, latest_reports_map.get(p.name)) for p in pm.list_platforms(include_disabled=True)]

@router.get("/warnings")
async def get_compatibility_warnings(config_mgr = Depends(get_config_manager)):
    """获取所有平台的发现兼容性故障告警列表。"""
    import json
    reports_dir = Path(config_mgr.project_root) / "reports"
    alerts_file = reports_dir / "compatibility_alerts.json"
    
    if not alerts_file.exists():
        return []
    
    try:
        with open(alerts_file, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"读取兼容性告警失败: {str(e)}"
        )

@router.get("/{name}", response_model=PlatformResponse)
async def get_platform(
    name: str,
    pm: PlatformManager = Depends(get_platform_manager),
    config_mgr = Depends(get_config_manager)
):
    """获取指定平台的配置信息。"""
    reports_dir = Path(config_mgr.project_root) / "reports"
    try:
        entry = pm.get_platform(name)
        return _to_response(entry, reports_dir)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))

@router.post("", response_model=PlatformResponse, status_code=status.HTTP_201_CREATED)
async def create_platform(
    data: PlatformCreate,
    pm: PlatformManager = Depends(get_platform_manager),
    config_mgr = Depends(get_config_manager)
):
    """新建平台配置。"""
    reports_dir = Path(config_mgr.project_root) / "reports"
    entry = PlatformEntry(
        name=data.name,
        base_url=data.base_url,
        api_key=data.api_key,
        website=data.website or "",
        notes=data.notes or "",
        hints=data.hints or {},
        discovery_handler=data.discovery_handler or "openai",
    )
    try:
        pm.add_platform(entry)
        return _to_response(entry, reports_dir)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

@router.put("/{name}", response_model=PlatformResponse)
async def update_platform(
    name: str,
    data: PlatformUpdate,
    pm: PlatformManager = Depends(get_platform_manager),
    config_mgr = Depends(get_config_manager)
):
    """修改指定平台的配置。"""
    reports_dir = Path(config_mgr.project_root) / "reports"
    updates = {}
    if data.name is not None:
        updates["name"] = data.name
    if data.base_url is not None:
        updates["base_url"] = data.base_url
    if data.api_key is not None:
        updates["api_key"] = data.api_key
    if data.website is not None:
        updates["website"] = data.website
    if data.notes is not None:
        updates["notes"] = data.notes
    if data.hints is not None:
        updates["hints"] = data.hints
    if data.discovery_handler is not None:
        updates["discovery_handler"] = data.discovery_handler

    try:
        new_name = updates.get("name", name)
        # 如果重命名了该平台，且磁盘上存在相关的物理报告，同步重命名报告文件名
        if new_name != name and reports_dir.exists():
            pattern = re.compile(rf"^{re.escape(name)}_探测报告_(\d{{6}})_(\d{{4}})\.md$")
            for file in reports_dir.glob("*.md"):
                match = pattern.match(file.name)
                if match:
                    date_str = match.group(1)
                    time_str = match.group(2)
                    new_filename = f"{new_name}_探测报告_{date_str}_{time_str}.md"
                    new_file_path = file.parent / new_filename
                    try:
                        file.rename(new_file_path)
                    except Exception:
                        pass

        pm.update_platform(name, updates)
        updated_entry = pm.get_platform(new_name)
        return _to_response(updated_entry, reports_dir)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))

@router.delete("/{name}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_platform(name: str, pm: PlatformManager = Depends(get_platform_manager)):
    """物理删除平台配置。"""
    try:
        pm.delete_platform(name)
        return
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))

@router.post("/{name}/toggle", response_model=PlatformResponse)
async def toggle_platform(
    name: str,
    data: PlatformToggle,
    pm: PlatformManager = Depends(get_platform_manager),
    config_mgr = Depends(get_config_manager)
):
    """启用或禁用指定平台。"""
    reports_dir = Path(config_mgr.project_root) / "reports"
    try:
        pm.toggle_platform(name, data.enabled)
        updated_entry = pm.get_platform(name)
        return _to_response(updated_entry, reports_dir)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
