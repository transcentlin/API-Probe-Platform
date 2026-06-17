# 修改历史 (Revision History)
# ==================================
# 版本: v1.3
# 日期: 2026-06-17
# 修改说明: 修复 OllamaAdapter.get_headers 缺失 Authorization 鉴权标头的问题，确保直连 Ollama Cloud API 时能顺利携带 Token 完成鉴权。
# ----------------------------------
# 版本: v1.2
# 日期: 2026-06-15
# 修改说明: 扩充 FormatAdapter 协议支持 default_endpoint 和 get_headers()；补全了 Anthropic 和 Gemini 适配器；新增 OpenAI Text、OpenAI Responses、Ollama、Cohere 以及 DashScope 原生格式适配器；使 Registry 在初始化时默认注册所有 8 类主流适配器。
# ==================================

"""FormatAdapter：格式适配器插件系统（详细设计 §2.5）。

职责：
    1. 定义 FormatAdapter 协议（插件接口）
    2. AdapterRegistry 注册表管理
    3. 支持 8 种主流 API 格式适配器的构造、解析与打分
"""
from __future__ import annotations

from typing import Optional, Protocol

import httpx

from ..constants import (
    FORMAT_OPENAI,
    FORMAT_OPENAI_TEXT,
    FORMAT_OPENAI_RESP,
    FORMAT_OLLAMA,
    FORMAT_ANTHROPIC,
    FORMAT_GEMINI,
    FORMAT_COHERE,
    FORMAT_DASHSCOPE,
)


# ──────────────────────────────────────────────────────────────────────────
# 插件协议（详细设计 §2.5）
# ──────────────────────────────────────────────────────────────────────────


class ParsedResponse:
    """解析后的响应数据（统一格式）。"""

    def __init__(
        self,
        content: Optional[str] = None,
        error: Optional[str] = None,
        raw: Optional[dict] = None,
    ):
        self.content = content  # 提取的文本内容
        self.error = error  # 错误信息（若有）
        self.raw = raw  # 原始响应体（用于调试）


class FormatAdapter(Protocol):
    """格式适配器协议（详细设计 §2.5 接口定义）。

    所有适配器必须实现此协议的属性和方法。
    """

    @property
    def name(self) -> str:
        """适配器名称，如 'openai_chat_completions'。"""
        ...

    @property
    def default_endpoint(self) -> str:
        """该格式推荐的默认探测端点（如 '/v1/chat/completions' 或 '/v1/messages'）。"""
        ...

    def get_headers(self, api_key: str) -> dict:
        """获取特定协议所需的 HTTP 头部（鉴权、版本等）。"""
        ...

    def build_probe_request(self, prompt: str, model: str, **kwargs) -> dict:
        """构造探针请求体（格式特定）。

        Args:
            prompt: 探针提示词
            model: 模型 ID
            **kwargs: 额外参数（如 max_tokens, temperature）

        Returns:
            请求体字典（将被 JSON 序列化）
        """
        ...

    def parse_response(self, response: httpx.Response) -> ParsedResponse:
        """解析响应，提取内容或错误。

        Args:
            response: httpx 响应对象

        Returns:
            ParsedResponse 对象
        """
        ...

    def score(self, response: httpx.Response) -> float:
        """根据响应特征打分 0~1，用于格式识别（Stage1）。

        打分逻辑：
            - 响应结构完全匹配 → 0.9~1.0
            - 部分匹配 → 0.5~0.8
            - 不匹配 → 0.0~0.3

        Args:
            response: httpx 响应对象

        Returns:
            置信度分数 0~1
        """
        ...


# ──────────────────────────────────────────────────────────────────────────
# 1. OpenAI Chat Completions 适配器
# ──────────────────────────────────────────────────────────────────────────


class OpenAIAdapter:
    """OpenAI Chat Completions 格式适配器。"""

    @property
    def name(self) -> str:
        return FORMAT_OPENAI

    @property
    def default_endpoint(self) -> str:
        return "/chat/completions"

    def get_headers(self, api_key: str) -> dict:
        return {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

    def build_probe_request(self, prompt: str, model: str, **kwargs) -> dict:
        return {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": kwargs.get("max_tokens", 100),
            "temperature": kwargs.get("temperature", 0.7),
        }

    def parse_response(self, response: httpx.Response) -> ParsedResponse:
        try:
            data = response.json()
        except Exception as e:
            return ParsedResponse(error=f"JSON 解析失败: {e}")

        if response.status_code != 200:
            error_msg = data.get("error", {}).get("message", str(data))
            return ParsedResponse(error=f"HTTP {response.status_code}: {error_msg}", raw=data)

        try:
            content = data["choices"][0]["message"]["content"]
            return ParsedResponse(content=content, raw=data)
        except (KeyError, IndexError, TypeError) as e:
            return ParsedResponse(error=f"响应结构异常: {e}", raw=data)

    def score(self, response: httpx.Response) -> float:
        try:
            data = response.json()
        except Exception:
            return 0.0

        score = 0.0
        if "choices" in data:
            score += 0.4
            if isinstance(data["choices"], list) and len(data["choices"]) > 0:
                choice = data["choices"][0]
                if "message" in choice:
                    score += 0.3
                    if "content" in choice["message"]:
                        score += 0.3

        if "model" in data:
            score += 0.05
        if "usage" in data:
            score += 0.05

        return min(score, 1.0)


# ──────────────────────────────────────────────────────────────────────────
# 2. OpenAI Legacy Completions 适配器
# ──────────────────────────────────────────────────────────────────────────


class OpenAITextAdapter:
    """OpenAI Legacy Text Completions 格式适配器。"""

    @property
    def name(self) -> str:
        return FORMAT_OPENAI_TEXT

    @property
    def default_endpoint(self) -> str:
        return "/completions"

    def get_headers(self, api_key: str) -> dict:
        return {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

    def build_probe_request(self, prompt: str, model: str, **kwargs) -> dict:
        return {
            "model": model,
            "prompt": prompt,
            "max_tokens": kwargs.get("max_tokens", 100),
            "temperature": kwargs.get("temperature", 0.7),
        }

    def parse_response(self, response: httpx.Response) -> ParsedResponse:
        try:
            data = response.json()
        except Exception as e:
            return ParsedResponse(error=f"JSON 解析失败: {e}")

        if response.status_code != 200:
            error_msg = data.get("error", {}).get("message", str(data))
            return ParsedResponse(error=f"HTTP {response.status_code}: {error_msg}", raw=data)

        try:
            content = data["choices"][0]["text"]
            return ParsedResponse(content=content, raw=data)
        except (KeyError, IndexError, TypeError) as e:
            return ParsedResponse(error=f"响应结构异常: {e}", raw=data)

    def score(self, response: httpx.Response) -> float:
        try:
            data = response.json()
        except Exception:
            return 0.0

        score = 0.0
        if "choices" in data:
            score += 0.4
            if isinstance(data["choices"], list) and len(data["choices"]) > 0:
                choice = data["choices"][0]
                if "text" in choice and "message" not in choice:
                    score += 0.4

        if "model" in data:
            score += 0.1
        if "usage" in data:
            score += 0.1

        return min(score, 1.0)


# ──────────────────────────────────────────────────────────────────────────
# 3. OpenAI Responses 适配器
# ──────────────────────────────────────────────────────────────────────────


class OpenAIResponseAdapter:
    """OpenAI Agent-oriented Responses 格式适配器。"""

    @property
    def name(self) -> str:
        return FORMAT_OPENAI_RESP

    @property
    def default_endpoint(self) -> str:
        return "/responses"

    def get_headers(self, api_key: str) -> dict:
        return {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

    def build_probe_request(self, prompt: str, model: str, **kwargs) -> dict:
        return {
            "model": model,
            "output": prompt,
        }

    def parse_response(self, response: httpx.Response) -> ParsedResponse:
        try:
            data = response.json()
        except Exception as e:
            return ParsedResponse(error=f"JSON 解析失败: {e}")

        if response.status_code != 200:
            return ParsedResponse(error=f"HTTP {response.status_code}: {data}", raw=data)

        try:
            output = data["output"]
            if isinstance(output, list) and len(output) > 0:
                content = output[0].get("body", {}).get("content", "")
            else:
                content = str(output)
            return ParsedResponse(content=content, raw=data)
        except Exception as e:
            return ParsedResponse(error=f"响应结构异常: {e}", raw=data)

    def score(self, response: httpx.Response) -> float:
        try:
            data = response.json()
        except Exception:
            return 0.0

        if "output" in data and "choices" not in data:
            return 0.95
        return 0.0


# ──────────────────────────────────────────────────────────────────────────
# 4. Ollama Native 适配器
# ──────────────────────────────────────────────────────────────────────────


class OllamaAdapter:
    """Ollama Native 格式适配器。"""

    @property
    def name(self) -> str:
        return FORMAT_OLLAMA

    @property
    def default_endpoint(self) -> str:
        return "/api/chat"

    def get_headers(self, api_key: str) -> dict:
        headers = {
            "Content-Type": "application/json",
        }
        if api_key and api_key != "ollama":
            headers["Authorization"] = f"Bearer {api_key}"
        return headers

    def build_probe_request(self, prompt: str, model: str, **kwargs) -> dict:
        return {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "stream": False,
            "options": {
                "temperature": kwargs.get("temperature", 0.7),
            }
        }

    def parse_response(self, response: httpx.Response) -> ParsedResponse:
        try:
            data = response.json()
        except Exception as e:
            return ParsedResponse(error=f"JSON 解析失败: {e}")

        if response.status_code != 200:
            return ParsedResponse(error=f"HTTP {response.status_code}: {data}", raw=data)

        try:
            content = data["message"]["content"]
            return ParsedResponse(content=content, raw=data)
        except (KeyError, TypeError) as e:
            return ParsedResponse(error=f"响应结构异常: {e}", raw=data)

    def score(self, response: httpx.Response) -> float:
        try:
            data = response.json()
        except Exception:
            return 0.0

        score = 0.0
        if "message" in data and "choices" not in data:
            score += 0.5
            message = data["message"]
            if isinstance(message, dict) and "content" in message:
                score += 0.4
        if "model" in data:
            score += 0.1

        return min(score, 1.0)


# ──────────────────────────────────────────────────────────────────────────
# 5. Anthropic Messages 适配器
# ──────────────────────────────────────────────────────────────────────────


class AnthropicAdapter:
    """Anthropic Messages 格式适配器。"""

    @property
    def name(self) -> str:
        return FORMAT_ANTHROPIC

    @property
    def default_endpoint(self) -> str:
        return "/messages"

    def get_headers(self, api_key: str) -> dict:
        return {
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
        }

    def build_probe_request(self, prompt: str, model: str, **kwargs) -> dict:
        return {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": kwargs.get("max_tokens", 100),
            "temperature": kwargs.get("temperature", 0.7),
        }

    def parse_response(self, response: httpx.Response) -> ParsedResponse:
        try:
            data = response.json()
        except Exception as e:
            return ParsedResponse(error=f"JSON 解析失败: {e}")

        if response.status_code != 200:
            error_msg = data.get("error", {}).get("message", str(data))
            return ParsedResponse(error=f"HTTP {response.status_code}: {error_msg}", raw=data)

        try:
            content = data["content"][0]["text"]
            return ParsedResponse(content=content, raw=data)
        except (KeyError, IndexError, TypeError) as e:
            return ParsedResponse(error=f"响应结构异常: {e}", raw=data)

    def score(self, response: httpx.Response) -> float:
        try:
            data = response.json()
        except Exception:
            return 0.0

        score = 0.0
        if "content" in data and "choices" not in data:
            score += 0.4
            if isinstance(data["content"], list) and len(data["content"]) > 0:
                content_item = data["content"][0]
                if isinstance(content_item, dict) and content_item.get("type") == "text":
                    score += 0.4
        if "role" in data and data["role"] == "assistant":
            score += 0.15
        if "id" in data and str(data["id"]).startswith("msg_"):
            score += 0.05

        return min(score, 1.0)


# ──────────────────────────────────────────────────────────────────────────
# 6. Gemini Native 适配器
# ──────────────────────────────────────────────────────────────────────────


class GeminiAdapter:
    """Gemini Native 格式适配器。"""

    @property
    def name(self) -> str:
        return FORMAT_GEMINI

    @property
    def default_endpoint(self) -> str:
        # 在 stages.py 实际请求时会将 {model} 替换为真实检测出的模型名
        return "/models/{model}:generateContent"

    def get_headers(self, api_key: str) -> dict:
        return {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

    def build_probe_request(self, prompt: str, model: str, **kwargs) -> dict:
        return {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "maxOutputTokens": kwargs.get("max_tokens", 100),
                "temperature": kwargs.get("temperature", 0.7),
            }
        }

    def parse_response(self, response: httpx.Response) -> ParsedResponse:
        try:
            data = response.json()
        except Exception as e:
            return ParsedResponse(error=f"JSON 解析失败: {e}")

        if response.status_code != 200:
            return ParsedResponse(error=f"HTTP {response.status_code}: {data}", raw=data)

        try:
            content = data["candidates"][0]["content"]["parts"][0]["text"]
            return ParsedResponse(content=content, raw=data)
        except (KeyError, IndexError, TypeError) as e:
            return ParsedResponse(error=f"响应结构异常: {e}", raw=data)

    def score(self, response: httpx.Response) -> float:
        try:
            data = response.json()
        except Exception:
            return 0.0

        score = 0.0
        if "candidates" in data and "choices" not in data:
            score += 0.4
            if isinstance(data["candidates"], list) and len(data["candidates"]) > 0:
                cand = data["candidates"][0]
                if "content" in cand and "parts" in cand["content"]:
                    score += 0.4
                    parts = cand["content"]["parts"]
                    if isinstance(parts, list) and len(parts) > 0 and "text" in parts[0]:
                        score += 0.2

        return min(score, 1.0)


# ──────────────────────────────────────────────────────────────────────────
# 7. Cohere Chat V2 适配器
# ──────────────────────────────────────────────────────────────────────────


class CohereAdapter:
    """Cohere Chat V2 格式适配器。"""

    @property
    def name(self) -> str:
        return FORMAT_COHERE

    @property
    def default_endpoint(self) -> str:
        return "/chat"

    def get_headers(self, api_key: str) -> dict:
        return {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

    def build_probe_request(self, prompt: str, model: str, **kwargs) -> dict:
        return {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
        }

    def parse_response(self, response: httpx.Response) -> ParsedResponse:
        try:
            data = response.json()
        except Exception as e:
            return ParsedResponse(error=f"JSON 解析失败: {e}")

        if response.status_code != 200:
            return ParsedResponse(error=f"HTTP {response.status_code}: {data}", raw=data)

        try:
            content = data["message"]["content"][0]["text"]
            return ParsedResponse(content=content, raw=data)
        except (KeyError, IndexError, TypeError) as e:
            return ParsedResponse(error=f"响应结构异常: {e}", raw=data)

    def score(self, response: httpx.Response) -> float:
        try:
            data = response.json()
        except Exception:
            return 0.0

        score = 0.0
        if "message" in data and "choices" not in data:
            msg = data["message"]
            if isinstance(msg, dict) and "content" in msg:
                score += 0.5
                content = msg["content"]
                if isinstance(content, list) and len(content) > 0 and "text" in content[0]:
                    score += 0.45

        return min(score, 1.0)


# ──────────────────────────────────────────────────────────────────────────
# 8. Alibaba DashScope 适配器
# ──────────────────────────────────────────────────────────────────────────


class DashScopeAdapter:
    """Alibaba DashScope Native 格式适配器。"""

    @property
    def name(self) -> str:
        return FORMAT_DASHSCOPE

    @property
    def default_endpoint(self) -> str:
        return "/services/aigc/text-generation/generation"

    def get_headers(self, api_key: str) -> dict:
        return {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

    def build_probe_request(self, prompt: str, model: str, **kwargs) -> dict:
        return {
            "model": model,
            "input": {
                "messages": [{"role": "user", "content": prompt}]
            },
            "parameters": {
                "result_format": "message"
            }
        }

    def parse_response(self, response: httpx.Response) -> ParsedResponse:
        try:
            data = response.json()
        except Exception as e:
            return ParsedResponse(error=f"JSON 解析失败: {e}")

        if response.status_code != 200:
            return ParsedResponse(error=f"HTTP {response.status_code}: {data}", raw=data)

        try:
            content = data["output"]["choices"][0]["message"]["content"]
            return ParsedResponse(content=content, raw=data)
        except (KeyError, IndexError, TypeError) as e:
            return ParsedResponse(error=f"响应结构异常: {e}", raw=data)

    def score(self, response: httpx.Response) -> float:
        try:
            data = response.json()
        except Exception:
            return 0.0

        score = 0.0
        if "output" in data and "choices" not in data:
            score += 0.5
            output = data["output"]
            if isinstance(output, dict) and "choices" in output:
                score += 0.4
        if "request_id" in data:
            score += 0.1

        return min(score, 1.0)


# ──────────────────────────────────────────────────────────────────────────
# 注册表管理（默认载入所有支持的适配器）
# ──────────────────────────────────────────────────────────────────────────


class AdapterRegistry:
    """格式适配器注册表。"""

    def __init__(self):
        self._adapters: dict[str, FormatAdapter] = {}
        # 默认注册所有适配器，确保旧入口文件自动兼容支持
        self.register(FORMAT_OPENAI, OpenAIAdapter())
        self.register(FORMAT_OPENAI_TEXT, OpenAITextAdapter())
        self.register(FORMAT_OPENAI_RESP, OpenAIResponseAdapter())
        self.register(FORMAT_OLLAMA, OllamaAdapter())
        self.register(FORMAT_ANTHROPIC, AnthropicAdapter())
        self.register(FORMAT_GEMINI, GeminiAdapter())
        self.register(FORMAT_COHERE, CohereAdapter())
        self.register(FORMAT_DASHSCOPE, DashScopeAdapter())

    def register(self, name: str, adapter: FormatAdapter) -> None:
        """注册适配器。"""
        self._adapters[name] = adapter

    def get(self, name: str) -> Optional[FormatAdapter]:
        """根据名称获取适配器。"""
        return self._adapters.get(name)

    def get_all(self) -> list[FormatAdapter]:
        """获取所有已注册适配器。"""
        return list(self._adapters.values())
