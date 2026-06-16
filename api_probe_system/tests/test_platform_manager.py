# -*- coding: utf-8 -*-
"""单元测试：PlatformManager（统一加密平台注册表管理器）。"""

import pytest
from pathlib import Path
from cryptography.fernet import InvalidToken

from api_probe_system.core.platform_manager import PlatformManager, PlatformEntry
from api_probe_system.core.vault import VaultDecryptError


@pytest.fixture
def temp_registry_path(tmp_path):
    """返回临时加密注册表路径，避免污染真实配置。"""
    return tmp_path / "platforms.enc"


class TestPlatformManager:
    """PlatformManager 加密读写与 CRUD 单元测试。"""

    def test_empty_registry(self, temp_registry_path):
        """测试不存在注册表文件时的加载情况。"""
        pm = PlatformManager(master_password="pw-123", registry_path=temp_registry_path)
        assert len(pm.list_platforms()) == 0
        assert not temp_registry_path.exists()

    def test_add_and_load(self, temp_registry_path):
        """测试添加平台并保存，然后重新加载。"""
        pm = PlatformManager(master_password="pw-123", registry_path=temp_registry_path)
        entry = PlatformEntry(
            name="BlazeAI",
            base_url="https://blazeai.boxu.dev/api",
            api_key="blz-key-xyz",
            enabled=True,
            notes="测试备注",
            website="https://blazeai.boxu.dev",
            hints={"format": "openai-chat"}
        )
        pm.add_platform(entry)
        assert temp_registry_path.exists()

        # 使用相同密码重新加载
        pm2 = PlatformManager(master_password="pw-123", registry_path=temp_registry_path)
        assert len(pm2.list_platforms()) == 1
        loaded = pm2.get_platform("BlazeAI")
        assert loaded.name == "BlazeAI"
        assert loaded.base_url == "https://blazeai.boxu.dev/api"
        assert loaded.api_key == "blz-key-xyz"
        assert loaded.enabled is True
        assert loaded.notes == "测试备注"
        assert loaded.website == "https://blazeai.boxu.dev"
        assert loaded.hints == {"format": "openai-chat"}

    def test_wrong_password_raises(self, temp_registry_path):
        """测试使用错误的密码加载会抛出 VaultDecryptError。"""
        pm = PlatformManager(master_password="right-pw", registry_path=temp_registry_path)
        pm.add_platform(PlatformEntry(name="P1", base_url="http://x", api_key="k"))

        with pytest.raises(VaultDecryptError):
            PlatformManager(master_password="wrong-pw", registry_path=temp_registry_path)

    def test_add_duplicate_raises(self, temp_registry_path):
        """测试添加重复平台名抛出 ValueError。"""
        pm = PlatformManager(master_password="pw", registry_path=temp_registry_path)
        pm.add_platform(PlatformEntry(name="P1", base_url="http://x", api_key="k"))
        
        with pytest.raises(ValueError, match="平台已存在"):
            pm.add_platform(PlatformEntry(name="P1", base_url="http://y", api_key="j"))

    def test_update_platform(self, temp_registry_path):
        """测试更新平台属性。"""
        pm = PlatformManager(master_password="pw", registry_path=temp_registry_path)
        entry = PlatformEntry(name="P1", base_url="http://x", api_key="k")
        pm.add_platform(entry)

        # 更新部分字段
        pm.update_platform("P1", {"base_url": "http://new-x", "enabled": False})
        loaded = pm.get_platform("P1")
        assert loaded.base_url == "http://new-x"
        assert loaded.enabled is False

        # 测试重命名冲突
        pm.add_platform(PlatformEntry(name="P2", base_url="http://y", api_key="k2"))
        with pytest.raises(ValueError, match="目标平台名已存在"):
            pm.update_platform("P1", {"name": "P2"})

        # 成功重命名
        pm.update_platform("P1", {"name": "P3"})
        with pytest.raises(ValueError, match="平台不存在"):
            pm.get_platform("P1")
        assert pm.get_platform("P3").base_url == "http://new-x"

    def test_delete_platform(self, temp_registry_path):
        """测试删除平台。"""
        pm = PlatformManager(master_password="pw", registry_path=temp_registry_path)
        pm.add_platform(PlatformEntry(name="P1", base_url="http://x", api_key="k"))
        assert len(pm.list_platforms()) == 1

        pm.delete_platform("P1")
        assert len(pm.list_platforms()) == 0
        with pytest.raises(ValueError, match="平台不存在"):
            pm.get_platform("P1")

    def test_list_platforms_filter(self, temp_registry_path):
        """测试是否过滤未启用平台。"""
        pm = PlatformManager(master_password="pw", registry_path=temp_registry_path)
        pm.add_platform(PlatformEntry(name="P1", base_url="http://x", api_key="k", enabled=True))
        pm.add_platform(PlatformEntry(name="P2", base_url="http://y", api_key="j", enabled=False))

        assert len(pm.list_platforms(include_disabled=True)) == 2
        assert len(pm.list_platforms(include_disabled=False)) == 1
        assert pm.list_platforms(include_disabled=False)[0].name == "P1"

    def test_to_platform_config(self, temp_registry_path):
        """测试转换为 Pydantic PlatformConfig 对象的兼容性。"""
        pm = PlatformManager(master_password="pw", registry_path=temp_registry_path)
        entry = PlatformEntry(
            name="BlazeAI",
            base_url="https://blazeai.boxu.dev/api",
            api_key="blz-key-xyz",
            website="https://blazeai.boxu.dev",
            notes="测试备注",
            hints={"format": "openai-chat", "models": ["gpt-4"]}
        )
        config = pm.to_platform_config(entry)

        from api_probe_system.core.models import PlatformConfig
        assert isinstance(config, PlatformConfig)
        assert config.name == "BlazeAI"
        assert config.base_url == "https://blazeai.boxu.dev/api"
        assert config.api_key == "blz-key-xyz"
        assert str(config.website) == "https://blazeai.boxu.dev/"
        assert config.notes == "测试备注"
        assert config.hints.format == "openai-chat"
        assert config.hints.models == ["gpt-4"]

    def test_clear_password(self, temp_registry_path):
        """测试安全清除内存密码。"""
        pm = PlatformManager(master_password="pw", registry_path=temp_registry_path)
        assert pm._master_password == "pw"
        pm.clear_password()
        assert pm._master_password is None
