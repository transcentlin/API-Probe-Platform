"""单元测试：EnvVault（加密保险箱）。"""
from __future__ import annotations

from unittest.mock import patch

import pytest

from api_probe_system.core.vault import EnvVault, VaultDecryptError, VaultError


@pytest.fixture
def temp_vault_path(tmp_path, monkeypatch):
    """临时 .env.enc 路径，避免污染真实文件。"""
    enc_path = tmp_path / ".env.enc"
    monkeypatch.setattr(EnvVault, "PATH", enc_path)
    monkeypatch.setattr(EnvVault, "_CONFIG_DIR", tmp_path)
    yield enc_path


@pytest.fixture(autouse=True)
def mock_keychain(monkeypatch):
    """Mock keyring，避免真实读写 OS Keychain。"""
    store: dict[tuple[str, str], str] = {}

    def fake_set(service, user, password):
        store[(service, user)] = password

    def fake_get(service, user):
        return store.get((service, user))

    def fake_delete(service, user):
        store.pop((service, user), None)

    monkeypatch.setattr("api_probe_system.core.vault.keyring.set_password", fake_set)
    monkeypatch.setattr("api_probe_system.core.vault.keyring.get_password", fake_get)
    monkeypatch.setattr("api_probe_system.core.vault.keyring.delete_password", fake_delete)
    yield store


class TestEncryptDecrypt:
    """加解密回环测试。"""

    def test_round_trip_basic(self, temp_vault_path):
        data = {"BlazeAI_API_KEY": "blz_xxx", "OPENROUTER_API_KEY": "sk-or-..."}
        EnvVault.encrypt(data, "master-pw-123")
        assert EnvVault.exists()
        result = EnvVault.decrypt("master-pw-123")
        assert result == data

    def test_round_trip_empty_dict(self, temp_vault_path):
        EnvVault.encrypt({}, "pw")
        assert EnvVault.decrypt("pw") == {}

    def test_round_trip_chinese(self, temp_vault_path):
        data = {"中文键名": "中文值🔐"}
        EnvVault.encrypt(data, "中文密码")
        assert EnvVault.decrypt("中文密码") == data

    def test_round_trip_long_password(self, temp_vault_path):
        long_pw = "x" * 256
        data = {"K": "V"}
        EnvVault.encrypt(data, long_pw)
        assert EnvVault.decrypt(long_pw) == data

    def test_round_trip_large_dict(self, temp_vault_path):
        data = {f"KEY_{i}": f"value_{i}" * 10 for i in range(100)}
        EnvVault.encrypt(data, "pw")
        assert EnvVault.decrypt("pw") == data

    def test_wrong_password_raises(self, temp_vault_path):
        EnvVault.encrypt({"K": "V"}, "right-pw")
        with pytest.raises(VaultDecryptError):
            EnvVault.decrypt("wrong-pw")

    def test_tampered_ciphertext_raises(self, temp_vault_path):
        EnvVault.encrypt({"K": "V"}, "pw")
        # 篡改密文最后 1 字节
        raw = temp_vault_path.read_bytes()
        tampered = raw[:-1] + bytes([raw[-1] ^ 0xFF])
        temp_vault_path.write_bytes(tampered)
        with pytest.raises(VaultDecryptError):
            EnvVault.decrypt("pw")

    def test_decrypt_nonexistent_raises(self, temp_vault_path):
        assert not EnvVault.exists()
        with pytest.raises(VaultError, match="加密文件不存在"):
            EnvVault.decrypt("pw")

    def test_encrypt_creates_parent_dir(self, tmp_path, monkeypatch):
        # 模拟 _CONFIG_DIR 不存在的情况
        nested = tmp_path / "deep" / "config"
        monkeypatch.setattr(EnvVault, "_CONFIG_DIR", nested)
        monkeypatch.setattr(EnvVault, "PATH", nested / ".env.enc")
        EnvVault.encrypt({"K": "V"}, "pw")
        assert (nested / ".env.enc").exists()


class TestKeychainOps:
    """OS Keychain 存取测试（已 mock）。"""

    def test_save_and_load(self, mock_keychain):
        EnvVault.save_master_to_keychain("my-pw")
        assert EnvVault.load_master_from_keychain() == "my-pw"

    def test_load_missing(self, mock_keychain):
        assert EnvVault.load_master_from_keychain() is None

    def test_delete(self, mock_keychain):
        EnvVault.save_master_to_keychain("pw")
        EnvVault.delete_master_from_keychain()
        assert EnvVault.load_master_from_keychain() is None

    def test_delete_missing_no_raise(self, mock_keychain):
        # 删除不存在的项不应抛错
        EnvVault.delete_master_from_keychain()


class TestKeyDerivation:
    """密钥派生稳定性。"""

    def test_same_password_same_salt_same_key(self):
        """相同密码 + 相同盐 → 相同密钥（确定性）。"""
        salt = b"\x01" * 16
        k1 = EnvVault._derive_fernet_key("pw", salt)
        k2 = EnvVault._derive_fernet_key("pw", salt)
        assert k1 == k2

    def test_different_password_different_key(self):
        salt = b"\x00" * 16
        assert EnvVault._derive_fernet_key("pw1", salt) != EnvVault._derive_fernet_key("pw2", salt)

    def test_different_salt_different_key(self):
        """相同密码 + 不同盐 → 不同密钥（随机盐的安全意义）。"""
        assert (
            EnvVault._derive_fernet_key("pw", b"\x00" * 16)
            != EnvVault._derive_fernet_key("pw", b"\xff" * 16)
        )
