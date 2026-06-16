# 修改历史 (Revision History)
# ==================================
# 版本: v1.3.2
# 日期: 2026-06-16
# 修改说明: 1) 新增 COMPARISON_PATTERN 正则解析规则以支持横向对比报告的单独分类（归入 "横向对比" 平台并准确还原创建时间）；2) list_reports 接口支持 platform="横向对比" 过滤条件下的精确定向 glob 对比报告提取。
# ----------------------------------
# 版本: v1.3.1
# 日期: 2026-06-16
# 修改说明: 对已存在的 Markdown 探测报告内容，引入完全 0-I/O 的内存缓存直接返回机制，彻底规避 baidu 同步盘上高频 stat() 造成的磁盘加载卡顿问题。
# ----------------------------------
# 版本: v1.3.0
# 日期: 2026-06-16
# 修改说明: 1) 挂载 GET /reports/latest 路由，实现基于文件名时间戳高可靠排序并读入最新报告内容返回；2) 引入全局 _CONTENT_CACHE 内容内存缓存，消除探测报告读取时的重复磁盘 I/O 阻塞。
# ----------------------------------
# 版本: v1.2.0
# 日期: 2026-06-16
# 修改说明: 在 list_reports 接口中增加零 I/O 字符串逆向排序和安全切片机制（限制最多 stat 30个文件），防百度同步盘同步文件句柄过多导致 I/O 卡顿。
# ----------------------------------
# 版本: v1.1.2
# 日期: 2026-06-16
# 修改说明: 在 list_reports 接口中增加 platform 过滤支持，在 glob 阶段精确定向匹配以大量削减 I/O 及 stat() 的耗时。
# ----------------------------------
# 版本: v1.1.1
# 日期: 2026-06-15
# 修改说明: 使用 CompareRequest Pydantic Schema 重构多平台对比生成接口以防 422 校验报错。
# ----------------------------------
# 版本: v1.1.0
# 日期: 2026-06-15
# 修改说明: 挂载横向对比 API 端点，支持多平台探测数据的结构化合并对比报告生成。
# ----------------------------------
# 版本: v1.0.0
# 日期: 2026-06-15
# 修改说明: 实现探测报告管理 API 路由，支持报告的列表发现、读取 Markdown 原文和删除操作。
# ==================================

# -*- coding: utf-8 -*-
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import PlainTextResponse
from api_probe_system.web.schemas import ReportResponse, CompareRequest
from api_probe_system.web.dependencies import get_config_manager
from api_probe_system.core.comparison_reporter import ComparisonReporter

router = APIRouter(prefix="/reports", tags=["Reports"])

# 全局报告内容缓存，格式为: { filename: (mtime, content) }
_CONTENT_CACHE: dict[str, tuple[float, str]] = {}

REPORT_PATTERN = re.compile(r"^(.+?)_探测报告_(\d{6}_\d{4})\.md$")
COMPARISON_PATTERN = re.compile(r"^Comparison_Report_(\d{6}_\d{4})\.md$")

def _parse_report_metadata(path: Path) -> ReportResponse:
    filename = path.name
    size_bytes = path.stat().st_size
    
    # 尝试匹配单平台探测报告
    match = REPORT_PATTERN.match(filename)
    if match:
        platform_name = match.group(1)
        raw_time = match.group(2)
        try:
            dt = datetime.strptime(raw_time, "%y%m%d_%H%M")
            created_at = dt.strftime("%Y-%m-%d %H:%M:%S")
        except Exception:
            created_at = datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S")
    else:
        # 尝试匹配多平台横向对比报告
        match_comp = COMPARISON_PATTERN.match(filename)
        if match_comp:
            platform_name = "横向对比"
            raw_time = match_comp.group(1)
            try:
                dt = datetime.strptime(raw_time, "%y%m%d_%H%M")
                created_at = dt.strftime("%Y-%m-%d %H:%M:%S")
            except Exception:
                created_at = datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S")
        else:
            platform_name = "Unknown"
            created_at = datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S")
        
    return ReportResponse(
        filename=filename,
        size_bytes=size_bytes,
        platform_name=platform_name,
        created_at=created_at
    )

@router.get("", response_model=list[ReportResponse])
async def list_reports(platform: Optional[str] = None, config_mgr = Depends(get_config_manager)):
    """获取所有历史探测报告的元数据列表（按创建时间倒序）。"""
    reports_dir = Path(config_mgr.project_root) / "reports"
    if not reports_dir.exists():
        return []
        
    if platform == "横向对比":
        # 定向匹配多平台对比报告
        md_files = [p for p in reports_dir.glob("Comparison_Report_*.md") if p.is_file()]
    elif platform:
        # 针对同步盘 I/O 阻塞：精确定向匹配该平台的报告，避免 stat 其它无关平台
        md_files = [p for p in reports_dir.glob(f"{platform}_探测报告_*.md") if p.is_file()]
    else:
        md_files = [p for p in reports_dir.glob("*.md") if p.is_file()]
        
    # 💥 针对同步盘优化 1：由于文件名后缀包含时间戳，直接利用文件名做字符串逆向排序
    md_files.sort(key=lambda p: p.name, reverse=True)
    
    # 💥 针对同步盘优化 2：切片取前 15 (单平台) 或 30 (全部) 个，大幅度减少对磁盘执行 stat() 获取文件大小的 I/O 次数
    limit = 15 if platform else 30
    md_files = md_files[:limit]
        
    reports = [_parse_report_metadata(p) for p in md_files]
    return reports

@router.get("/latest", response_class=PlainTextResponse)
async def get_latest_report(platform: str, config_mgr = Depends(get_config_manager)):
    """获取指定平台最新创建时间（基于文件名时间戳排序）探测报告的 Markdown 原文。"""
    reports_dir = Path(config_mgr.project_root) / "reports"
    if not reports_dir.exists():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="报告目录不存在")
        
    # 精确 glob 匹配该平台的所有报告
    files = list(reports_dir.glob(f"{platform}_探测报告_*.md"))
    if not files:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"该平台 {platform} 暂无探测报告")
        
    # 基于文件名降序排序（文件名后缀 yymmdd_HHMM 精准对齐时间先后顺序，排在第 1 的必为最新报告）
    files.sort(key=lambda p: p.name, reverse=True)
    latest_file = files[0]
    filename = latest_file.name
    
    try:
        # 💥 优化：报告文件为一次性静态落盘，内存缓存命中时直接返回 0 I/O，规避 stat() 系统调用
        if filename in _CONTENT_CACHE:
            return _CONTENT_CACHE[filename][1]
            
        mtime = latest_file.stat().st_mtime
        # 缓存未命中，执行文件读取并刷清缓存
        content = latest_file.read_text(encoding="utf-8")
        _CONTENT_CACHE[filename] = (mtime, content)
        return content
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"加载最新报告内容失败: {e}"
        )

@router.get("/{filename}", response_class=PlainTextResponse)
async def get_report_content(filename: str, config_mgr = Depends(get_config_manager)):
    """获取指定报告的 Markdown 原文。"""
    reports_dir = Path(config_mgr.project_root) / "reports"
    file_path = reports_dir / filename
    
    # 路径安全防护（防跨目录遍历攻击）
    try:
        if not file_path.resolve().relative_to(reports_dir.resolve()):
             raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="非法的文件路径")
    except ValueError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="非法的文件路径")
         
    if not file_path.exists():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="报告文件不存在")
        
    try:
        # 💥 优化：直接内存缓存命中 0 I/O 返回，跳过 stat() 系统调用以防同步盘阻塞
        if filename in _CONTENT_CACHE:
            return _CONTENT_CACHE[filename][1]
            
        mtime = file_path.stat().st_mtime
        content = file_path.read_text(encoding="utf-8")
        _CONTENT_CACHE[filename] = (mtime, content)
        return content
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"读取报告内容失败: {e}"
        )

@router.delete("/{filename}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_report(filename: str, config_mgr = Depends(get_config_manager)):
    """删除指定的报告文件。"""
    reports_dir = Path(config_mgr.project_root) / "reports"
    file_path = reports_dir / filename
    
    # 路径安全防护
    try:
        if not file_path.resolve().relative_to(reports_dir.resolve()):
             raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="非法的文件路径")
    except ValueError:
         raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="非法的文件路径")
         
    if not file_path.exists():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="报告文件不存在")
        
    try:
        file_path.unlink()
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"文件删除失败: {e}"
        )
    return

@router.post("/compare")
async def generate_comparison(
    data: Optional[CompareRequest] = None,
    config_mgr = Depends(get_config_manager)
):
    """手动触发生成多个平台横向对比报告。"""
    reports_dir = Path(config_mgr.project_root) / "reports"
    platforms = data.platforms if data else None
    try:
        output_path = ComparisonReporter.generate_comparison_report(
            reports_dir=reports_dir,
            platform_names=platforms
        )
        return {
            "filename": output_path.name,
            "status": "success",
            "message": f"横向对比报告已生成: {output_path.name}"
        }
    except ValueError as ve:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(ve))
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"生成对比报告失败: {e}"
        )
