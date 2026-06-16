# 修改历史 (Revision History)
# ==================================
# 版本: v1.1.0
# 日期: 2026-06-15
# 修改说明: 在 discover 方法中支持可选参数 model_status，使得 OpenAIDiscoveryHandler 可以收集原生模型状态以用于 Stage 2.5 短路。
# ==================================

# -*- coding: utf-8 -*-
"""registry.py：专属平台模型发现程序库与注册表。"""

import json
import httpx
from typing import Optional, Any
from ..models import PlatformConfig

class BaseDiscoveryHandler:
    """模型发现处理器基类。"""
    @property
    def name(self) -> str:
        raise NotImplementedError

    async def discover(
        self, 
        client: httpx.AsyncClient, 
        base_url: str, 
        api_key: str, 
        platform: PlatformConfig,
        model_status: Optional[dict[str, str]] = None
    ) -> list[str]:
        """具体的模型列表获取逻辑。"""
        raise NotImplementedError


class OpenAIDiscoveryHandler(BaseDiscoveryHandler):
    """标准的 OpenAI 模型发现处理器。"""
    @property
    def name(self) -> str:
        return "openai"

    async def discover(
        self, 
        client: httpx.AsyncClient, 
        base_url: str, 
        api_key: str, 
        platform: PlatformConfig,
        model_status: Optional[dict[str, str]] = None
    ) -> list[str]:
        models_url = f"{base_url.rstrip('/')}/models"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        
        response = await client.get(models_url, headers=headers)
        if response.status_code != 200:
            raise httpx.HTTPStatusError(
                f"HTTP {response.status_code}: {response.text[:200]}",
                request=response.request,
                response=response
            )
            
        data = response.json()
        models = []
        if isinstance(data, list):
            for m in data:
                if isinstance(m, dict):
                    model_id = m.get("id") or m.get("name")
                    if model_id:
                        models.append(model_id)
                        if model_status is not None and "status" in m:
                            model_status[model_id] = str(m["status"])
        elif isinstance(data, dict) and "data" in data:
            for m in data["data"]:
                if isinstance(m, dict) and "id" in m:
                    models.append(m["id"])
                    if model_status is not None and "status" in m:
                        model_status[m["id"]] = str(m["status"])
        else:
            raise ValueError(f"响应格式不符合预期: {str(data)[:200]}")
            
        return models


class OllamaDiscoveryHandler(BaseDiscoveryHandler):
    """Ollama 专属模型发现处理器（/api/tags）。"""
    @property
    def name(self) -> str:
        return "ollama"

    async def discover(
        self, 
        client: httpx.AsyncClient, 
        base_url: str, 
        api_key: str, 
        platform: PlatformConfig,
        model_status: Optional[dict[str, str]] = None
    ) -> list[str]:
        # 提取 native api 前缀 http://host:port/api
        url = base_url.rstrip('/')
        if not url.endswith("/api"):
            if url.endswith("/v1"):
                url = url[:-3] + "/api"
            else:
                url = url + "/api"
        tags_url = f"{url}/tags"
        
        headers = {
            "Content-Type": "application/json",
        }
        # Ollama 云端需要 Authorization，本地可能忽略但加了无妨
        if api_key and api_key != "ollama":
            headers["Authorization"] = f"Bearer {api_key}"
            
        response = await client.get(tags_url, headers=headers)
        if response.status_code != 200:
            raise httpx.HTTPStatusError(
                f"HTTP {response.status_code}: {response.text[:200]}",
                request=response.request,
                response=response
            )
            
        data = response.json()
        if not (isinstance(data, dict) and "models" in data):
            raise ValueError(f"响应格式不符合预期: {str(data)[:200]}")
            
        models = []
        for m in data["models"]:
            if isinstance(m, dict) and "name" in m:
                models.append(m["name"])
        return models


class CloudflareDiscoveryHandler(BaseDiscoveryHandler):
    """Cloudflare Workers AI 专属模型发现处理器（/ai/models/search）。"""
    @property
    def name(self) -> str:
        return "cloudflare"

    async def discover(
        self, 
        client: httpx.AsyncClient, 
        base_url: str, 
        api_key: str, 
        platform: PlatformConfig,
        model_status: Optional[dict[str, str]] = None
    ) -> list[str]:
        # 智能替换 /ai/v1 结尾为 /ai/models/search
        search_url = base_url.replace("/ai/v1", "/ai/models/search")
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        
        response = await client.get(search_url, headers=headers)
        if response.status_code != 200:
            raise httpx.HTTPStatusError(
                f"HTTP {response.status_code}: {response.text[:200]}",
                request=response.request,
                response=response
            )
            
        data = response.json()
        if not (isinstance(data, dict) and data.get("success") and "result" in data):
            raise ValueError(f"响应格式不符合预期: {str(data)[:200]}")
            
        models = []
        for m in data["result"]:
            if isinstance(m, dict) and "name" in m:
                models.append(m["name"])
        return models


class ModelDiscoveryRegistry:
    """模型发现处理器注册表。"""
    def __init__(self):
        self._handlers = {}
        self.register(OpenAIDiscoveryHandler())
        self.register(OllamaDiscoveryHandler())
        self.register(CloudflareDiscoveryHandler())

    def register(self, handler: BaseDiscoveryHandler):
        self._handlers[handler.name] = handler

    def get(self, name: str) -> BaseDiscoveryHandler:
        if name not in self._handlers:
            raise KeyError(f"未找到已注册的模型发现处理器: {name}")
        return self._handlers[name]


# 全局单例注册表
discovery_registry = ModelDiscoveryRegistry()
