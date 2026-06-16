# -*- coding: utf-8 -*-
"""PlatformManager：统一加密平台注册表管理器。

核心职责：
1. 加密加载和保存 platforms.enc 文件。
2. 提供对平台条目的 CRUD 操作。
3. 转换解密后的条目为 Pydantic 的 PlatformConfig 供引擎直接使用。
"""

import json
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional, Any
from .vault import EnvVault


@dataclass
class PlatformEntry:
    """单个平台条目（解密后的内存表示）。"""
    name: str
    base_url: str
    api_key: str
    enabled: bool = True
    notes: str = ""
    website: str = ""
    hints: dict = field(default_factory=dict)
    discovery_handler: str = "openai"


class PlatformManager:
    """统一加密平台注册表管理器。"""

    REGISTRY_PATH = Path(__file__).resolve().parent.parent / "config" / "platforms.enc"

    def __init__(self, master_password: str, registry_path: Optional[Path] = None):
        self._master_password = master_password
        self.registry_path = registry_path or self.REGISTRY_PATH
        self._platforms: list[PlatformEntry] = []
        self._load()

    def _load(self) -> None:
        """解密 platforms.enc 并加载至内存。"""
        if not self.registry_path.exists():
            self._platforms = []
            return

        try:
            ciphertext = self.registry_path.read_bytes()
            plaintext = EnvVault.decrypt_bytes(ciphertext, self._master_password)
            data = json.loads(plaintext.decode("utf-8"))
            self._platforms = []
            for item in data.get("platforms", []):
                self._platforms.append(PlatformEntry(
                    name=item["name"],
                    base_url=item["base_url"],
                    api_key=item["api_key"],
                    enabled=item.get("enabled", True),
                    notes=item.get("notes", ""),
                    website=item.get("website", ""),
                    hints=item.get("hints", {}) or {},
                    discovery_handler=item.get("discovery_handler", "openai"),
                ))
        except Exception as e:
            # 向上抛出异常（例如解密失败）以供上层感知
            raise e

    def _save(self) -> None:
        """将当前内存中的平台列表加密保存至文件。"""
        self.registry_path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "platforms": [
                {
                    "name": p.name,
                    "base_url": p.base_url,
                    "api_key": p.api_key,
                    "enabled": p.enabled,
                    "notes": p.notes,
                    "website": p.website,
                    "hints": p.hints,
                    "discovery_handler": p.discovery_handler,
                }
                for p in self._platforms
            ]
        }
        plaintext = json.dumps(data, ensure_ascii=False).encode("utf-8")
        ciphertext = EnvVault.encrypt_bytes(plaintext, self._master_password)
        self.registry_path.write_bytes(ciphertext)

    def list_platforms(self, include_disabled: bool = True) -> list[PlatformEntry]:
        """列出所有平台条目。"""
        if include_disabled:
            return self._platforms
        return [p for p in self._platforms if p.enabled]

    def get_platform(self, name: str) -> PlatformEntry:
        """获取指定名称的平台。"""
        for p in self._platforms:
            if p.name == name:
                return p
        raise ValueError(f"平台不存在: {name}")

    def add_platform(self, entry: PlatformEntry) -> None:
        """添加新平台，并自动保存。"""
        if any(p.name == entry.name for p in self._platforms):
            raise ValueError(f"平台已存在: {entry.name}")
        self._platforms.append(entry)
        self._save()

    def update_platform(self, name: str, updates: dict[str, Any]) -> None:
        """更新平台属性，并自动保存。"""
        p = self.get_platform(name)
        
        # 检查重命名冲突
        if "name" in updates and updates["name"] != name:
            if any(other.name == updates["name"] for other in self._platforms):
                raise ValueError(f"目标平台名已存在: {updates['name']}")
            p.name = updates["name"]
            
        if "base_url" in updates:
            p.base_url = updates["base_url"]
        if "api_key" in updates:
            p.api_key = updates["api_key"]
        if "enabled" in updates:
            p.enabled = updates["enabled"]
        if "notes" in updates:
            p.notes = updates["notes"]
        if "website" in updates:
            p.website = updates["website"]
        if "hints" in updates:
            p.hints = updates["hints"] or {}
        if "discovery_handler" in updates:
            p.discovery_handler = updates["discovery_handler"]
            
        self._save()

    def delete_platform(self, name: str) -> None:
        """删除指定平台，并自动保存。"""
        p = self.get_platform(name)
        self._platforms.remove(p)
        self._save()

    def toggle_platform(self, name: str, enabled: bool) -> None:
        """启用或禁用指定平台。"""
        self.update_platform(name, {"enabled": enabled})

    def to_platform_config(self, entry: PlatformEntry) -> Any:
        """将条目转换为引擎直接可用的 Pydantic PlatformConfig 对象。"""
        from .models import PlatformConfig, Hints
        
        website = None
        if entry.website and entry.website.strip():
            website = entry.website.strip()
            
        hints = None
        if entry.hints:
            hints = Hints(
                format=entry.hints.get("format"),
                models=entry.hints.get("models"),
                endpoints=entry.hints.get("endpoints")
            )
            
        return PlatformConfig(
            name=entry.name,
            base_url=entry.base_url,
            api_key=entry.api_key,
            website=website,
            notes=entry.notes or None,
            hints=hints,
            discovery_handler=entry.discovery_handler
        )

    def clear_password(self) -> None:
        """安全清除内存中的主密码。"""
        self._master_password = None
