"""单元测试：ConfigManager（不依赖网络）。"""
from pathlib import Path
from tempfile import NamedTemporaryFile

import pytest

from api_probe_system.core.config import ConfigManager, ConfigStore
from api_probe_system.core.constants import ConfigError
from api_probe_system.core.secret import SecretResolver


class TestConfigStore:
    """测试 ConfigStore YAML 加载。"""

    def test_load_valid_config(self):
        """测试加载有效配置。"""
        yaml_content = """
platforms:
  - name: TestPlatform
    base_url: https://api.example.com
    api_key: sk-test123
    website: https://example.com
    notes: 测试平台
"""
        with NamedTemporaryFile(mode="w", suffix=".yaml", delete=False, encoding="utf-8") as f:
            f.write(yaml_content)
            config_path = Path(f.name)

        try:
            store = ConfigStore(config_path)
            config = store.load()
            assert len(config.platforms) == 1
            assert config.platforms[0].name == "TestPlatform"
            assert str(config.platforms[0].base_url) == "https://api.example.com"
        finally:
            config_path.unlink()

    def test_load_missing_file(self):
        """测试文件不存在时抛出 ConfigError。"""
        store = ConfigStore(Path("/nonexistent/config.yaml"))
        with pytest.raises(ConfigError, match="配置文件不存在"):
            store.load()

    def test_load_invalid_yaml(self):
        """测试 YAML 格式错误。"""
        yaml_content = """
platforms:
  - name: Test
    base_url: [invalid
"""
        with NamedTemporaryFile(mode="w", suffix=".yaml", delete=False, encoding="utf-8") as f:
            f.write(yaml_content)
            config_path = Path(f.name)

        try:
            store = ConfigStore(config_path)
            with pytest.raises(ConfigError, match="YAML 格式错误"):
                store.load()
        finally:
            config_path.unlink()

    def test_load_missing_required_field(self):
        """测试缺少必填字段时校验失败。"""
        yaml_content = """
platforms:
  - name: Test
    # 缺少 base_url 和 api_key
"""
        with NamedTemporaryFile(mode="w", suffix=".yaml", delete=False, encoding="utf-8") as f:
            f.write(yaml_content)
            config_path = Path(f.name)

        try:
            store = ConfigStore(config_path)
            with pytest.raises(ConfigError, match="配置校验失败"):
                store.load()
        finally:
            config_path.unlink()


class TestConfigManager:
    """测试 ConfigManager 配置管理。"""

    @pytest.fixture
    def valid_config_file(self):
        """创建有效配置文件。"""
        yaml_content = """
platforms:
  - name: Platform1
    base_url: https://api1.example.com
    api_key: sk-plain-key
  - name: Platform2
    base_url: https://api2.example.com
    api_key: ${TEST_ENV_KEY}
"""
        with NamedTemporaryFile(mode="w", suffix=".yaml", delete=False, encoding="utf-8") as f:
            f.write(yaml_content)
            temp_path = Path(f.name)

        yield temp_path

        # 确保文件关闭后再删除
        try:
            temp_path.unlink()
        except PermissionError:
            pass  # Windows 文件锁，忽略

    def test_load_and_list_platforms(self, valid_config_file):
        """测试加载配置并列出平台。"""
        store = ConfigStore(valid_config_file)
        manager = ConfigManager(store, SecretResolver())
        manager.load()

        platforms = manager.list_platforms()
        assert len(platforms) == 2
        assert platforms[0].name == "Platform1"
        assert platforms[1].name == "Platform2"

    def test_get_platform_by_name(self, valid_config_file):
        """测试根据名称获取平台。"""
        store = ConfigStore(valid_config_file)
        manager = ConfigManager(store, SecretResolver())
        manager.load()

        platform = manager.get_platform("Platform1")
        assert platform.name == "Platform1"
        assert str(platform.base_url) == "https://api1.example.com"

    def test_get_nonexistent_platform(self, valid_config_file):
        """测试获取不存在的平台。"""
        store = ConfigStore(valid_config_file)
        manager = ConfigManager(store, SecretResolver())
        manager.load()

        with pytest.raises(ConfigError, match="平台 'Nonexistent' 不存在"):
            manager.get_platform("Nonexistent")

    def test_resolve_api_key_plain(self, valid_config_file):
        """测试解析明文密钥。"""
        store = ConfigStore(valid_config_file)
        manager = ConfigManager(store, SecretResolver())
        manager.load()

        platform = manager.get_platform("Platform1")
        key = manager.resolve_api_key(platform)
        assert key == "sk-plain-key"

    def test_resolve_api_key_env(self, valid_config_file, monkeypatch):
        """测试解析环境变量密钥。"""
        monkeypatch.setenv("TEST_ENV_KEY", "env-secret-value")

        store = ConfigStore(valid_config_file)
        manager = ConfigManager(store, SecretResolver())
        manager.load()

        platform = manager.get_platform("Platform2")
        key = manager.resolve_api_key(platform)
        assert key == "env-secret-value"

    def test_validate_platform_success(self, valid_config_file):
        """测试平台配置校验通过。"""
        store = ConfigStore(valid_config_file)
        manager = ConfigManager(store, SecretResolver())
        manager.load()

        platform = manager.get_platform("Platform1")
        errors = manager.validate_platform(platform)
        assert errors == []
