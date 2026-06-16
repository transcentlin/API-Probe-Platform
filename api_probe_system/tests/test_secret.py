"""单元测试：SecretResolver（不依赖网络）。"""
import os

import pytest

from api_probe_system.core.constants import ConfigError
from api_probe_system.core.secret import SecretResolver


class TestSecretResolver:
    """测试 SecretResolver 密钥解析与脱敏。"""

    def test_resolve_plain_key(self):
        """测试明文密钥直接返回。"""
        plain_key = "sk-1234567890abcdef"
        result = SecretResolver.resolve(plain_key)
        assert result == plain_key

    def test_resolve_env_var_success(self, monkeypatch):
        """测试 ${ENV} 引用成功解析。"""
        monkeypatch.setenv("TEST_API_KEY", "secret-value-from-env")
        result = SecretResolver.resolve("${TEST_API_KEY}")
        assert result == "secret-value-from-env"

    def test_resolve_env_var_missing(self):
        """测试环境变量未设置且 vault 未加载时抛出 ConfigError。"""
        SecretResolver.clear_vault()  # 确保 vault 缓存清空
        with pytest.raises(ConfigError, match="NONEXISTENT_VAR"):
            SecretResolver.resolve("${NONEXISTENT_VAR}")

    def test_resolve_vault_priority(self, monkeypatch):
        """测试 vault 缓存优先于环境变量。"""
        monkeypatch.setenv("DUAL_KEY", "from-env")
        SecretResolver._vault_cache = {"DUAL_KEY": "from-vault"}
        try:
            assert SecretResolver.resolve("${DUAL_KEY}") == "from-vault"
        finally:
            SecretResolver.clear_vault()

    def test_resolve_vault_fallback_to_env(self, monkeypatch):
        """测试 vault 中没有时回退到环境变量。"""
        monkeypatch.setenv("ONLY_ENV", "env-value")
        SecretResolver._vault_cache = {"OTHER_KEY": "x"}
        try:
            assert SecretResolver.resolve("${ONLY_ENV}") == "env-value"
        finally:
            SecretResolver.clear_vault()

    def test_mask_standard_key(self):
        """测试标准长度密钥脱敏（保留前 4 + 后 4）。"""
        key = "sta_2046c8e0d4bbe"
        masked = SecretResolver.mask(key)
        assert masked == "sta_...4bbe"
        assert len(masked) < len(key)

    def test_mask_short_key(self):
        """测试短密钥脱敏（保留前 2 + 后 2）。"""
        key = "short"
        masked = SecretResolver.mask(key)
        assert masked == "sh...rt"

    def test_mask_preserves_prefix_suffix(self):
        """测试脱敏保留前后缀特征（用于日志识别）。"""
        key = "blz_1234567890abcdef"
        masked = SecretResolver.mask(key)
        assert masked.startswith("blz_")
        assert masked.endswith("cdef")
        assert "..." in masked
