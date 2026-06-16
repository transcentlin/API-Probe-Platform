# 修改历史 (Revision History)
# ==================================
# 版本: v1.0.0
# 日期: 2026-06-15
# 修改说明: 编写集成测试，测试 FastAPI 的平台 CRUD 接口、报告管理接口及未解锁状态的 403 边界。
# ==================================

# -*- coding: utf-8 -*-
import pytest
from fastapi.testclient import TestClient
from api_probe_system.web.app import create_app
from api_probe_system.core.platform_manager import PlatformManager, PlatformEntry
from api_probe_system.core.vault import EnvVault

@pytest.fixture
def unauthenticated_client():
    app = create_app()
    # 不注入 platform_manager
    return TestClient(app)

@pytest.fixture
def authenticated_client(tmp_path):
    app = create_app()
    # 模拟加密注册表
    reg_file = tmp_path / "platforms.enc"
    pw = "test_password_123"
    
    # 实例化并解密
    pm = PlatformManager(pw, registry_path=reg_file)
    # 注入测试数据
    entry = PlatformEntry(
        name="TestPlatform",
        base_url="https://api.test.com/v1",
        api_key="sk-testkey1234567890",
        website="https://test.com",
        notes="Just a test platform"
    )
    pm.add_platform(entry)
    
    # 初始化全局配置依赖
    class MockConfig:
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
        project_root = str(tmp_path)

    app.state.platform_manager = pm
    app.state.config_manager = MockConfig()
    
    return TestClient(app)

def test_health_check(unauthenticated_client):
    """测试健康检查端点（无需解锁）。"""
    response = unauthenticated_client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "message": "API Probe Station 后端运行正常"}

def test_unauthenticated_crud_raises_403(unauthenticated_client):
    """未解锁时，CRUD 接口应返回 403。"""
    response = unauthenticated_client.get("/api/platforms")
    assert response.status_code == 403
    assert "请先使用主密码解锁" in response.json()["detail"]

def test_list_platforms_authenticated(authenticated_client):
    """测试获取已解锁状态下的平台列表。"""
    response = authenticated_client.get("/api/platforms")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["name"] == "TestPlatform"
    # 检查 api_key 已经正确脱敏
    assert data[0]["api_key"] == "sk-t...7890"

def test_get_platform_detail(authenticated_client):
    """测试获取平台详情。"""
    response = authenticated_client.get("/api/platforms/TestPlatform")
    assert response.status_code == 200
    assert response.json()["name"] == "TestPlatform"

def test_platform_not_found(authenticated_client):
    response = authenticated_client.get("/api/platforms/NonExistent")
    assert response.status_code == 404

def test_create_platform(authenticated_client):
    """测试新建平台接口。"""
    payload = {
        "name": "NewPlatform",
        "base_url": "https://api.new.com/v1",
        "api_key": "sk-newkey987654321",
        "website": "https://new.com",
        "notes": "new notes",
        "hints": {},
        "discovery_handler": "openai"
    }
    response = authenticated_client.post("/api/platforms", json=payload)
    assert response.status_code == 201
    assert response.json()["name"] == "NewPlatform"
    assert response.json()["api_key"] == "sk-n...4321"

def test_create_platform_duplicate_raises_400(authenticated_client):
    """测试新建重名平台冲突。"""
    payload = {
        "name": "TestPlatform",
        "base_url": "https://api.test.com/v1",
        "api_key": "sk-key",
    }
    response = authenticated_client.post("/api/platforms", json=payload)
    assert response.status_code == 400
    assert "平台已存在" in response.json()["detail"]

def test_update_platform(authenticated_client):
    """测试更新平台属性。"""
    payload = {
        "base_url": "https://api.test-updated.com/v2",
        "notes": "updated notes"
    }
    response = authenticated_client.put("/api/platforms/TestPlatform", json=payload)
    assert response.status_code == 200
    assert response.json()["base_url"] == "https://api.test-updated.com/v2"
    assert response.json()["notes"] == "updated notes"

def test_delete_platform(authenticated_client):
    """测试删除平台。"""
    response = authenticated_client.delete("/api/platforms/TestPlatform")
    assert response.status_code == 204
    # 再次查询，应返回 404
    assert authenticated_client.get("/api/platforms/TestPlatform").status_code == 404

def test_toggle_platform(authenticated_client):
    """测试启用/禁用切换。"""
    # 禁用
    response = authenticated_client.post("/api/platforms/TestPlatform/toggle", json={"enabled": False})
    assert response.status_code == 200
    assert response.json()["enabled"] is False

def test_list_reports_empty(authenticated_client):
    """测试空报告列表。"""
    response = authenticated_client.get("/api/reports")
    assert response.status_code == 200
    assert response.json() == []

def test_get_report_not_found(authenticated_client):
    response = authenticated_client.get("/api/reports/non_existent.md")
    assert response.status_code == 404

def test_get_compatibility_warnings(authenticated_client):
    """测试获取兼容性告警列表。"""
    response = authenticated_client.get("/api/platforms/warnings")
    assert response.status_code == 200
    assert isinstance(response.json(), list)
