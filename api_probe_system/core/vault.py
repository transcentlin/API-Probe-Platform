"""EnvVault：加密 .env 保险箱。

设计：
    - cryptography.Fernet 对称加密（AES-128-CBC + HMAC-SHA256）
    - PBKDF2HMAC-SHA256 从主密码派生密钥（200000 轮）
    - 主密码存 OS Keychain（keyring 库）
    - 文件内容是 dict[str, str]，加密前用 UTF-8 编码为 JSON

文件格式（与 configcrypt/KeyVault 兼容）：
    [字节 0-15]   随机盐（16 字节，每次加密重新生成）
    [字节 16+]    Fernet 加密数据

    OS Keychain   api-probe-system / master-password → 用户主密码

不走环境变量回退：主密码只能从 Keychain 取，或交互式输入。
"""
from __future__ import annotations

import base64
import json
import os
from pathlib import Path

import keyring
from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC


class VaultError(Exception):
    """保险箱通用错误。"""


class VaultDecryptError(VaultError):
    """主密码错误或密文被篡改时抛出。"""


class EnvVault:
    """加密 .env 保险箱。

    用法：
        EnvVault.encrypt({"BlazeAI_API_KEY": "blz_..."}, "master_password")
        data = EnvVault.decrypt("master_password")     # 解密后返回 dict

        EnvVault.save_master_to_keychain("master_password")
        pw = EnvVault.load_master_from_keychain()
    """

    # 文件路径（项目根目录的 config/.env.enc）
    _CONFIG_DIR = Path(__file__).resolve().parent.parent / "config"
    PATH = _CONFIG_DIR / ".env.enc"

    SALT_SIZE = 16          # 随机盐字节数（与 configcrypt 格式一致）
    KDF_ITERATIONS = 200_000

    # OS Keychain 标识
    KEYCHAIN_SERVICE = "api-probe-system"
    KEYCHAIN_USER = "master-password"

    # ──────────────────────────────────────────────────────────────────
    # 派生密钥
    # ──────────────────────────────────────────────────────────────────

    @classmethod
    def _derive_fernet_key(cls, master_password: str, salt: bytes) -> bytes:
        """主密码 + 盐值 → 32 字节 Fernet key（base64 编码）。"""
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=salt,
            iterations=cls.KDF_ITERATIONS,
        )
        raw = kdf.derive(master_password.encode("utf-8"))
        return base64.urlsafe_b64encode(raw)

    # ──────────────────────────────────────────────────────────────────
    # 文件读写
    # ──────────────────────────────────────────────────────────────────

    @classmethod
    def exists(cls) -> bool:
        """加密文件是否存在。"""
        return cls.PATH.exists()

    @classmethod
    def encrypt(cls, data: dict, master_password: str) -> None:
        """加密 dict 并写入 PATH。格式：[16B 随机盐][Fernet 密文]。"""
        cls._CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        salt = os.urandom(cls.SALT_SIZE)
        key = cls._derive_fernet_key(master_password, salt)
        fernet = Fernet(key)
        plaintext = json.dumps(data, ensure_ascii=False).encode("utf-8")
        ciphertext = fernet.encrypt(plaintext)
        cls.PATH.write_bytes(salt + ciphertext)

    @classmethod
    def decrypt(cls, master_password: str) -> dict:
        """从 PATH 读取并解密为 dict。

        文件格式：[16B 随机盐][Fernet 密文]（与 configcrypt 兼容）。

        Raises:
            VaultError: 文件不存在或格式非法
            VaultDecryptError: 主密码错或密文被篡改
        """
        if not cls.exists():
            raise VaultError(f"加密文件不存在: {cls.PATH}")
        raw = cls.PATH.read_bytes()
        if len(raw) < cls.SALT_SIZE:
            raise VaultError("加密文件格式无效：文件过小")
        salt = raw[:cls.SALT_SIZE]
        ciphertext = raw[cls.SALT_SIZE:]
        key = cls._derive_fernet_key(master_password, salt)
        fernet = Fernet(key)
        try:
            plaintext = fernet.decrypt(ciphertext)
        except InvalidToken as e:
            raise VaultDecryptError("主密码错误或密文被篡改") from e
        plaintext_str = plaintext.decode("utf-8").strip()
        # 兼容两种内容格式：
        #   1. 我们自己加密的 JSON dict（以 { 开头）
        #   2. configcrypt 直接加密的 .env 文件（KEY=VALUE 文本）
        if plaintext_str.startswith("{"):
            return json.loads(plaintext_str)
        return cls._parse_env_text(plaintext_str)

    # ──────────────────────────────────────────────────────────────────
    # 内容格式辅助
    # ──────────────────────────────────────────────────────────────────

    @staticmethod
    def _parse_env_text(text: str) -> dict[str, str]:
        """解析 .env 文本（KEY=VALUE）为 dict，容忍 # 注释、空行、可选引号。"""
        result: dict[str, str] = {}
        for raw_line in text.splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
                value = value[1:-1]
            if key:
                result[key] = value
        return result

    # ──────────────────────────────────────────────────────────────────
    # 通用字节流加解密（任意文件用）
    # ──────────────────────────────────────────────────────────────────

    @classmethod
    def encrypt_bytes(cls, plaintext: bytes, master_password: str) -> bytes:
        """对任意字节流加密，返回 [16B 随机盐][Fernet 密文]。"""
        salt = os.urandom(cls.SALT_SIZE)
        key = cls._derive_fernet_key(master_password, salt)
        return salt + Fernet(key).encrypt(plaintext)

    @classmethod
    def decrypt_bytes(cls, ciphertext: bytes, master_password: str) -> bytes:
        """对任意字节流解密，输入格式 [16B 盐][Fernet 密文]，返回原始字节。

        Raises:
            VaultDecryptError: 主密码错或密文被篡改
        """
        salt = ciphertext[:cls.SALT_SIZE]
        data = ciphertext[cls.SALT_SIZE:]
        key = cls._derive_fernet_key(master_password, salt)
        try:
            return Fernet(key).decrypt(data)
        except InvalidToken as e:
            raise VaultDecryptError("主密码错误或密文被篡改") from e

    # ──────────────────────────────────────────────────────────────────
    # Keychain 操作
    # ──────────────────────────────────────────────────────────────────

    @classmethod
    def save_master_to_keychain(cls, master_password: str) -> None:
        """主密码写入 OS Keychain。"""
        keyring.set_password(cls.KEYCHAIN_SERVICE, cls.KEYCHAIN_USER, master_password)

    @classmethod
    def load_master_from_keychain(cls) -> str | None:
        """从 OS Keychain 读取主密码；不存在返回 None。"""
        return keyring.get_password(cls.KEYCHAIN_SERVICE, cls.KEYCHAIN_USER)

    @classmethod
    def delete_master_from_keychain(cls) -> None:
        """从 OS Keychain 删除主密码（reset 用）。"""
        try:
            keyring.delete_password(cls.KEYCHAIN_SERVICE, cls.KEYCHAIN_USER)
        except keyring.errors.PasswordDeleteError:
            pass  # 不存在视为已删除
