# 修改历史 (Revision History)
# ==================================
# 版本: v1.0.1
# 日期: 2026-06-15
# 修改说明: 修正 MOCK 报告格式以包含 10 列能力矩阵，并放宽对比报告行数测试的断言。
# ----------------------------------
# 版本: v1.0.0
# 日期: 2026-06-15
# 修改说明: 新建打分与解析的专有单元与集成测试，覆盖 ReportParser, PlatformScorer, ComparisonReporter 以及 FastAPI 相关的接口整合。
# ==================================

# -*- coding: utf-8 -*-
import pytest
from pathlib import Path
from datetime import datetime
from fastapi.testclient import TestClient

from api_probe_system.core.report_parser import ReportParser
from api_probe_system.core.scoring import PlatformScorer
from api_probe_system.core.comparison_reporter import ComparisonReporter
from api_probe_system.web.app import create_app
from api_probe_system.core.platform_manager import PlatformManager, PlatformEntry

# Mock Markdown 报告模版
MOCK_REPORT_CONTENT = """# BlazeAI 探测报告

📊 执行摘要
| 平台健康度 | 模型可用率 | 可用 / 总数 | 推荐首选 |
| :---: | :---: | :---: | :---: |
| 🟢 **良好** | **80.0%** | 4 / 5 | `mock-best-model` |

一、平台概览
| 指标 | 探测结果 |
| :--- | :--- |
| 可达性 | ✅ 可达（500 ms） |

三、推荐模型
| 排名 | 模型 ID | 支持能力详情 | 延迟 (ms) |
| :---: | :--- | :--- | :---: |
| 🥇 | `mock-best-model` | 流式、非流式 | 800 ms |

四、可用模型能力矩阵
| 模型 | 流式 | 非流式 | 工具调用 | 视觉 | JSON | 推理 | 联网 | 多轮 | 支持数 |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| `mock-best-model` | ✓ | ✓ | ✓ | ✗ | ✓ | ✓ | ✓ | ✓ | 7 |
| `mock-second-model` | ✓ | ✓ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | 2 |
"""

MOCK_BROKEN_REPORT_CONTENT = """# Broken 探测报告

📊 执行摘要
| 平台健康度 | 模型可用率 | 可用 / 总数 | 推荐首选 |
| :---: | :---: | :---: | :---: |
| 🔴 **差** | **0.0%** | 0 / 10 | — |

一、平台概览
| 指标 | 探测结果 |
| :--- | :--- |
| 可达性 | ❌ 不可达（—） |
"""

def test_report_parser(tmp_path):
    """测试 ReportParser 能够正确提取 Markdown 报告的数据。"""
    report_file = tmp_path / "BlazeAI_探测报告_260615_1852.md"
    report_file.write_text(MOCK_REPORT_CONTENT, encoding="utf-8")

    data = ReportParser.parse_file(report_file)
    assert data["platform_name"] == "BlazeAI"
    assert data["health_level"] == "良好"
    assert data["availability_rate"] == 80.0
    assert data["available_count"] == 4
    assert data["total_count"] == 5
    assert data["latency_ms"] == 500
    assert data["recommended_model"] == "mock-best-model"
    assert data["recommended_latency_ms"] == 800
    
    # 检查能力矩阵解析
    assert len(data["models_matrix"]) == 2
    m1 = data["models_matrix"][0]
    assert m1["model_name"] == "mock-best-model"
    assert m1["streaming"] is True
    assert m1["non_streaming"] is True
    # mock-best-model 高级能力支持情况: 工具调用(✓=1), 视觉(✗=0), JSON(✓=1), 推理(✓=1), 联网(✓=1), 多轮(✓=1) -> [1.0, 0.0, 1.0, 1.0, 1.0, 1.0]
    assert m1["advanced_caps"] == [1.0, 0.0, 1.0, 1.0, 1.0, 1.0]

    m2 = data["models_matrix"][1]
    assert m2["model_name"] == "mock-second-model"
    assert m2["streaming"] is True
    assert m2["non_streaming"] is True
    assert m2["advanced_caps"] == [0.0, 0.0, 0.0, 0.0, 0.0, 0.0]

def test_report_parser_broken_file(tmp_path):
    """测试 ReportParser 处理不可达和不可用时的容错。"""
    report_file = tmp_path / "Broken_探测报告_260615_1852.md"
    report_file.write_text(MOCK_BROKEN_REPORT_CONTENT, encoding="utf-8")

    data = ReportParser.parse_file(report_file)
    assert data["platform_name"] == "Broken"
    assert data["health_level"] == "差"
    assert data["availability_rate"] == 0.0
    assert data["latency_ms"] is None
    assert data["recommended_latency_ms"] is None
    assert len(data["models_matrix"]) == 0

def test_scoring_melting():
    """测试评分逻辑的熔断（不可达或可用数为0直接判定0分）。"""
    # 熔断1：不可达
    data_no_reach = {
        "latency_ms": None,
        "available_count": 4,
        "availability_rate": 80.0
    }
    assert PlatformScorer.calculate_score(data_no_reach) == 0.0

    # 熔断2：可用模型数为0
    data_no_models = {
        "latency_ms": 500,
        "available_count": 0,
        "availability_rate": 0.0
    }
    assert PlatformScorer.calculate_score(data_no_models) == 0.0

def test_scoring_normal_calculation():
    """测试评分逻辑正常计算下的各种扣分与权重组合。"""
    # 1. 满分情况
    data_perfect = {
        "latency_ms": 300,
        "availability_rate": 100.0,
        "available_count": 1,
        "recommended_latency_ms": 500, # <= 1s -> 100.0
        "models_matrix": [
            {
                "model_name": "perfect-model",
                "streaming": True,
                "non_streaming": True,
                "advanced_caps": [1.0] * 6 # 100.0
            }
        ]
    }
    # 40% * 100 + 30% * 100 + 30% * 100 = 100.0
    assert PlatformScorer.calculate_score(data_perfect) == 100.0

    # 2. 扣分情况
    # 基础分 = 80.0% -> 80.0 -> 权重得分 = 32.0
    # 推荐首选模型时延 = 2000ms -> 1s~3s扣分公式：90.0 - (2000 - 1000) / 100 * 2.5 = 90.0 - 25 = 65.0 -> 权重得分 = 19.5
    # 高级能力：
    # 模型1: [1.0, 0.0, 1.0, 1.0, 1.0, 1.0] -> 5/6 * 100 = 83.333
    # 模型2: [0.0, 0.0, 0.0, 0.0, 0.0, 0.0] -> 0.0
    # 平均高级能力支持率 = (83.333 + 0.0) / 2 = 41.667 -> 权重得分 = 12.50
    # 总得分 = 32.0 + 19.5 + 12.5 = 64.0
    data_deduct = {
        "latency_ms": 500,
        "availability_rate": 80.0,
        "available_count": 2,
        "recommended_latency_ms": 2000,
        "models_matrix": [
            {
                "model_name": "model1",
                "streaming": True,
                "non_streaming": True,
                "advanced_caps": [1.0, 0.0, 1.0, 1.0, 1.0, 1.0]
            },
            {
                "model_name": "model2",
                "streaming": True,
                "non_streaming": True,
                "advanced_caps": [0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
            }
        ]
    }
    score = PlatformScorer.calculate_score(data_deduct)
    assert score == 64.0

def test_comparison_reporter(tmp_path):
    """测试 ComparisonReporter 能正确提取并排序多份报告，生成对比 Markdown。"""
    # 写入两份报告
    reports_dir = tmp_path / "reports"
    reports_dir.mkdir()
    
    (reports_dir / "BlazeAI_探测报告_260615_1852.md").write_text(MOCK_REPORT_CONTENT, encoding="utf-8")
    (reports_dir / "Broken_探测报告_260615_1853.md").write_text(MOCK_BROKEN_REPORT_CONTENT, encoding="utf-8")
    
    output_path = ComparisonReporter.generate_comparison_report(reports_dir)
    assert output_path.exists()
    
    content = output_path.read_text(encoding="utf-8")
    assert "# 📊 API 平台横向对比分析报告" in content
    assert "BlazeAI" in content
    assert "Broken" in content
    # BlazeAI 应该排第一（62.0 分左右），Broken 应该排第二（0.0 分）
    lines = [line for line in content.splitlines() if "BlazeAI" in line or "Broken" in line]
    assert len(lines) >= 4
    
    # 校验排序，BlazeAI 的行应该在 Broken 的行之前
    idx_blaze = content.index("BlazeAI")
    idx_broken = content.index("Broken")
    assert idx_blaze < idx_broken

@pytest.fixture
def mock_web_app_client(tmp_path):
    app = create_app()
    # 注入 Mock 注册表
    reg_file = tmp_path / "platforms.enc"
    pm = PlatformManager("test_pwd", registry_path=reg_file)
    pm.add_platform(PlatformEntry(
        name="BlazeAI",
        base_url="https://api.blaze.com",
        api_key="sk-key123",
        website="https://blaze.com",
        notes="Mock Blaze"
    ))
    
    # 创建 Mock reports 目录
    reports_dir = tmp_path / "reports"
    reports_dir.mkdir()
    (reports_dir / "BlazeAI_探测报告_260615_1852.md").write_text(MOCK_REPORT_CONTENT, encoding="utf-8")
    
    class MockConfig:
        project_root = str(tmp_path)
        defaults = type("Defaults", (), {
            "timeouts": type("Timeouts", (), {
                "fast_threshold_ms": 3000,
                "slow_threshold_ms": 10000,
                "connect_timeout_s": 5.0
            })(),
            "deep_probe": type("DeepProbe", (), {
                "top_n": 3
            })()
        })()

    app.state.platform_manager = pm
    app.state.config_manager = MockConfig()
    
    return TestClient(app)

def test_api_platform_response_scoring_integration(mock_web_app_client):
    """测试 GET /api/platforms 响应中正确附带了 score 与 top_models。"""
    response = mock_web_app_client.get("/api/platforms")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    plat = data[0]
    assert plat["name"] == "BlazeAI"
    # score 应该是计算出的评分，而不是 None
    assert plat["score"] is not None
    assert plat["score"] > 50.0
    # top_models 应该成功拿到前三个模型，这里 mock 了两个模型，按降序应该包含 ['mock-best-model', 'mock-second-model']
    assert plat["top_models"] == ["mock-best-model", "mock-second-model"]

def test_api_reports_compare_endpoint(mock_web_app_client):
    """测试 POST /api/reports/compare 触发生成横向对比报告的集成。"""
    response = mock_web_app_client.post("/api/reports/compare", json={"platforms": ["BlazeAI"]})
    assert response.status_code == 200
    res_data = response.json()
    assert res_data["status"] == "success"
    assert "Comparison_Report_" in res_data["filename"]
