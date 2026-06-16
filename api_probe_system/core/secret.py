"""SecretResolver：密钥解析与脱敏（详细设计 §2.7 + §8）。

职责：
    1. 解析 ${ENV_VAR} 引用：优先从 EnvVault 解密后的内存表查询，找不到再回退到
       系统环境变量（兜底调试用，正式部署应全部走 vault）。
    2. 脱敏密钥用于日志/报告/UI 显示（NFR-SEC-02）。

启动顺序：
    - 入口脚本调一次 SecretResolver.load_vault(master_password) 把解密后的
      键值表灌进类级缓存。
    - 之后所有 resolve() 调用都从缓存优先取。
"""
from __future__ import annotations

import os

from .constants import ConfigError


class SecretResolver:
    """密钥解析与脱敏工具（详细设计 §8.2）。"""

    # 类级缓存：从 EnvVault 解密出来的键值表。入口启动时填入。
    _vault_cache: dict[str, str] | None = None

    # ──────────────────────────────────────────────────────────────────
    # Vault 加载
    # ──────────────────────────────────────────────────────────────────

    @classmethod
    def load_vault(cls, master_password: str) -> None:
        """用主密码解密 .env.enc 并灌入缓存。

        Raises:
            VaultDecryptError: 主密码错或密文被篡改（由调用方捕获）
            VaultError: 加密文件不存在
        """
        from .vault import EnvVault
        cls._vault_cache = EnvVault.decrypt(master_password)

    @classmethod
    def clear_vault(cls) -> None:
        """清空缓存（测试用 / 重新初始化用）。"""
        cls._vault_cache = None

    @classmethod
    def vault_loaded(cls) -> bool:
        """检查是否已加载 vault。"""
        return cls._vault_cache is not None

    # ──────────────────────────────────────────────────────────────────
    # 解析
    # ──────────────────────────────────────────────────────────────────

    @classmethod
    def resolve(cls, api_key: str) -> str:
        """解析 API 密钥。

        解析顺序：
            1. 明文（不匹配 ${...}）→ 原样返回
            2. ${VAR}：先查 vault 缓存，找不到回退到 os.getenv
            3. 都没有 → ConfigError

        Args:
            api_key: 原始密钥字符串（明文或 ${ENV} 引用）

        Returns:
            解析后的实际密钥

        Raises:
            ConfigError: 引用的变量在 vault 和环境变量中均不存在
        """
        if not (api_key.startswith("${") and api_key.endswith("}")):
            return api_key

        var_name = api_key[2:-1]

        # 1. 优先查 vault 缓存
        if cls._vault_cache is not None and var_name in cls._vault_cache:
            return cls._vault_cache[var_name]

        # 2. 回退到 OS 环境变量（兜底）
        value = os.getenv(var_name)
        if value is not None:
            return value

        # 3. 都没有
        if cls._vault_cache is not None:
            raise ConfigError(
                f"密钥 {var_name} 未在加密保险箱中找到。"
                f"请运行 `python tools/manage_keys.py add {var_name}` 添加。"
            )
        raise ConfigError(
            f"密钥 {var_name} 未在系统环境变量中找到，且加密保险箱未加载。"
            f"请运行 `python tools/manage_keys.py init` 初始化加密保险箱。"
        )

    # ──────────────────────────────────────────────────────────────────
    # 脱敏
    # ──────────────────────────────────────────────────────────────────

    @staticmethod
    def mask(secret: str) -> str:
        """脱敏密钥：保留前 4 位 + 后 4 位，中间用 ... 替代（详细设计 §8.1）。

        应用场景（NFR-SEC-02）：
            - API 响应（GET /platforms）
            - WebSocket 日志消息
            - 报告生成（MD/HTML）
            - 数据库存储请求头（Authorization 字段）

        Args:
            secret: 原始密钥

        Returns:
            脱敏后的密钥字符串

        Examples:
            >>> SecretResolver.mask("sta_2046c8e0d4bbe")
            'sta_...4bbe'
            >>> SecretResolver.mask("short")
            'sh...rt'
        """
        if len(secret) <= 12:
            return secret[:2] + "..." + secret[-2:]
        return secret[:4] + "..." + secret[-4:]
