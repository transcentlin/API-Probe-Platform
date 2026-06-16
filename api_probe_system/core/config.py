# 修改历史 (Revision History)
# ==================================
# 版本: v1.1
# 日期: 2026-06-15
# 修改说明: 改造 ConfigManager，使其支持从 PlatformManager 动态加载平台配置，替代从 YAML 直接加载 platforms，增强安全性。
# ==================================

"""ConfigManager：配置读取、校验与管理（详细设计 §2.7）。

职责：
    1. 从 user_config.yaml 加载平台配置（FR-CFG-01）
    2. 校验配置完整性与格式（FR-CFG-05）
    3. 解析密钥引用（调用 SecretResolver）
    4. 提供平台查询接口
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional, Any

import yaml
from pydantic import ValidationError

from .constants import (
    ConfigError,
    DEFAULT_CONNECT_TIMEOUT_S,
    DEFAULT_FAST_THRESHOLD_MS,
    DEFAULT_SLOW_THRESHOLD_MS,
)
from .models import PlatformConfig, ProbeTimeouts, UserConfig
from .secret import SecretResolver
from .platform_manager import PlatformManager


class ConfigStore:
    """ConfigStore：YAML 配置文件读取（详细设计 §3.3）。

    只读操作，不回写 user_config.yaml（FR-CFG-07）。
    """

    def __init__(self, config_path: Path):
        """初始化配置存储。

        Args:
            config_path: user_config.yaml 文件路径
        """
        self.config_path = config_path

    def load(self) -> UserConfig:
        """加载并解析 user_config.yaml。

        Returns:
            解析后的 UserConfig 对象

        Raises:
            ConfigError: 文件不存在、YAML 格式错误、Schema 校验失败
        """
        if not self.config_path.exists():
            raise ConfigError(
                f"配置文件不存在: {self.config_path}\n"
                f"请创建 user_config.yaml 并配置至少一个平台。"
            )

        try:
            with open(self.config_path, "r", encoding="utf-8") as f:
                raw_data = yaml.safe_load(f)
        except yaml.YAMLError as e:
            raise ConfigError(f"YAML 格式错误: {e}")

        if raw_data is None or not raw_data:
            raise ConfigError("配置文件为空")

        try:
            return UserConfig.model_validate(raw_data)
        except ValidationError as e:
            # Pydantic v2 错误格式化
            errors = "\n".join(
                f"  - {err['loc'][0] if err['loc'] else 'root'}: {err['msg']}"
                for err in e.errors()
            )
            raise ConfigError(f"配置校验失败:\n{errors}")


class ConfigManager:
    """ConfigManager：配置管理与平台查询（详细设计 §2.7）。"""

    def __init__(self, config_store: ConfigStore, platform_manager: PlatformManager | SecretResolver | None = None):
        """初始化配置管理器。

        Args:
            config_store: 配置存储实例
            platform_manager: 平台管理器实例或密钥解析器（兼容旧版）
        """
        self._store = config_store
        
        # 识别传入的类型以做兼容处理
        if isinstance(platform_manager, PlatformManager):
            self._pm = platform_manager
            self._resolver = None
        else:
            self._pm = None
            self._resolver = platform_manager
            
        self._config: Optional[UserConfig] = None
        self._platforms_by_name: dict[str, PlatformConfig] = {}

    def load(self) -> None:
        """加载配置并构建索引。

        Raises:
            ConfigError: 配置加载或校验失败
        """
        self._config = self._store.load()
        
        if self._pm is not None:
            # 新逻辑：从 PlatformManager 读取
            self._platforms_by_name = {}
            for entry in self._pm.list_platforms(include_disabled=True):
                self._platforms_by_name[entry.name] = self._pm.to_platform_config(entry)
        else:
            # 兼容旧逻辑：直接从 YAML 解析的 platforms 读取
            self._platforms_by_name = {p.name: p for p in self._config.platforms}

        # 检查平台名唯一性
        expected_len = len(self._config.platforms) if self._pm is None else len(self._platforms_by_name)
        if len(self._platforms_by_name) != expected_len:
            raise ConfigError("平台名称重复，每个平台的 name 必须唯一")

    def get_platform(self, name: str) -> PlatformConfig:
        """根据名称获取平台配置。

        Args:
            name: 平台名称

        Returns:
            平台配置对象

        Raises:
            ConfigError: 平台不存在
        """
        if not self._config:
            raise ConfigError("配置未加载，请先调用 load()")

        platform = self._platforms_by_name.get(name)
        if not platform:
            raise ConfigError(
                f"平台 '{name}' 不存在。可用平台: {list(self._platforms_by_name.keys())}"
            )
        return platform

    def list_platforms(self) -> list[PlatformConfig]:
        """获取所有平台配置列表。

        Returns:
            平台配置列表

        Raises:
            ConfigError: 配置未加载
        """
        if not self._config:
            raise ConfigError("配置未加载，请先调用 load()")
        
        if self._pm is not None:
            return list(self._platforms_by_name.values())
        return self._config.platforms

    def resolve_api_key(self, platform: PlatformConfig) -> str:
        """解析平台的 API 密钥（处理 ${ENV} 引用）。

        Args:
            platform: 平台配置

        Returns:
            解析后的实际密钥
        """
        if self._pm is not None:
            return platform.api_key
            
        if self._resolver is not None:
            return self._resolver.resolve(platform.api_key)
            
        return platform.api_key

    def get_deep_probe_top_n(self) -> int:
        """从 defaults.deep_probe.top_n 读取 Stage4/5 模型覆盖数量，默认 3。"""
        if not self._config:
            raise ConfigError("配置未加载，请先调用 load()")
        defaults = self._config.defaults
        if defaults and defaults.deep_probe:
            return defaults.deep_probe.top_n
        return 3

    def get_probe_timeouts(self) -> ProbeTimeouts:
        """从 defaults.timeouts 节构造 ProbeTimeouts。

        缺失字段使用 constants 中的默认值（30s / 60s / 10s）。

        Returns:
            ProbeTimeouts 实例

        Raises:
            ConfigError: 配置未加载
        """
        if not self._config:
            raise ConfigError("配置未加载，请先调用 load()")

        fast = DEFAULT_FAST_THRESHOLD_MS
        slow = DEFAULT_SLOW_THRESHOLD_MS
        connect = DEFAULT_CONNECT_TIMEOUT_S

        defaults = self._config.defaults
        if defaults and defaults.timeouts:
            t = defaults.timeouts
            if t.fast_threshold_ms is not None:
                fast = t.fast_threshold_ms
            if t.slow_threshold_ms is not None:
                slow = t.slow_threshold_ms
            if t.connect_timeout_s is not None:
                connect = t.connect_timeout_s

        # 校验：fast 不能 > slow，否则三级分类失效
        if fast > slow:
            raise ConfigError(
                f"defaults.timeouts 配置不合法：fast_threshold_ms({fast}) "
                f"不能大于 slow_threshold_ms({slow})"
            )

        return ProbeTimeouts(
            fast_threshold_ms=fast,
            slow_threshold_ms=slow,
            connect_timeout_s=connect,
        )

    def validate_platform(self, platform: PlatformConfig) -> list[str]:
        """校验单个平台配置（对应 FR-CFG-05）。

        Args:
            platform: 待校验的平台配置

        Returns:
            错误列表（空列表表示校验通过）
        """
        errors = []

        # 必填字段已由 Pydantic 校验，这里做业务逻辑校验
        if not platform.name.strip():
            errors.append("name 不能为空")

        # 尝试解析密钥
        try:
            self._resolver.resolve(platform.api_key)
        except ConfigError as e:
            errors.append(str(e))

        return errors
