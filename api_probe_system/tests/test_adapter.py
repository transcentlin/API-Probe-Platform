"""单元测试：OpenAIAdapter（不依赖网络，使用 mock 响应）。"""
import httpx
import pytest

from api_probe_system.core.adapters.base import AdapterRegistry, OpenAIAdapter


class TestOpenAIAdapter:
    """测试 OpenAI 格式适配器。"""

    @pytest.fixture
    def adapter(self):
        """创建 OpenAIAdapter 实例。"""
        return OpenAIAdapter()

    def test_adapter_name(self, adapter):
        """测试适配器名称。"""
        assert adapter.name == "openai_chat_completions"

    def test_build_probe_request(self, adapter):
        """测试构造请求体。"""
        request = adapter.build_probe_request("Hello", "gpt-3.5-turbo")
        assert request["model"] == "gpt-3.5-turbo"
        assert request["messages"] == [{"role": "user", "content": "Hello"}]
        assert "max_tokens" in request
        assert "temperature" in request

    def test_parse_response_success(self, adapter):
        """测试解析成功响应。"""
        # 模拟 OpenAI 成功响应
        mock_response = httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": "Hi there!"
                        }
                    }
                ],
                "model": "gpt-3.5-turbo",
                "usage": {"total_tokens": 10}
            }
        )

        parsed = adapter.parse_response(mock_response)
        assert parsed.content == "Hi there!"
        assert parsed.error is None

    def test_parse_response_http_error(self, adapter):
        """测试解析 HTTP 错误响应。"""
        mock_response = httpx.Response(
            401,
            json={
                "error": {
                    "message": "Invalid API key"
                }
            }
        )

        parsed = adapter.parse_response(mock_response)
        assert parsed.content is None
        assert "401" in parsed.error
        assert "Invalid API key" in parsed.error

    def test_parse_response_malformed(self, adapter):
        """测试解析格式异常响应。"""
        mock_response = httpx.Response(
            200,
            json={"unexpected": "structure"}
        )

        parsed = adapter.parse_response(mock_response)
        assert parsed.content is None
        assert "响应结构异常" in parsed.error

    def test_score_perfect_match(self, adapter):
        """测试完美匹配的打分。"""
        mock_response = httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": "Response"
                        }
                    }
                ],
                "model": "gpt-3.5-turbo",
                "usage": {"total_tokens": 10}
            }
        )

        score = adapter.score(mock_response)
        assert score >= 0.9  # 完美匹配应该高分

    def test_score_partial_match(self, adapter):
        """测试部分匹配的打分。"""
        mock_response = httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {}  # 缺少 content
                    }
                ]
            }
        )

        score = adapter.score(mock_response)
        assert 0.5 < score < 0.9  # 部分匹配中等分

    def test_score_no_match(self, adapter):
        """测试不匹配的打分。"""
        mock_response = httpx.Response(
            200,
            json={"completely": "different"}
        )

        score = adapter.score(mock_response)
        assert score < 0.3  # 不匹配低分


class TestAdapterRegistry:
    """测试适配器注册表。"""

    def test_register_and_get(self):
        """测试注册与获取适配器。"""
        registry = AdapterRegistry()
        adapter = OpenAIAdapter()

        registry.register("openai_custom", adapter)
        retrieved = registry.get("openai_custom")

        assert retrieved is adapter

    def test_get_nonexistent(self):
        """测试获取不存在的适配器。"""
        registry = AdapterRegistry()
        assert registry.get("nonexistent") is None

    def test_get_all(self):
        """测试获取所有适配器。"""
        registry = AdapterRegistry()
        all_adapters = registry.get_all()
        # 默认会自动注册 8 个适配器
        assert len(all_adapters) == 8


class TestAnthropicAdapter:
    @pytest.fixture
    def adapter(self):
        from api_probe_system.core.adapters.base import AnthropicAdapter
        return AnthropicAdapter()

    def test_build_request(self, adapter):
        req = adapter.build_probe_request("Hello", "claude-3-opus")
        assert req["model"] == "claude-3-opus"
        assert req["messages"][0]["content"] == "Hello"

    def test_parse_response(self, adapter):
        resp = httpx.Response(200, json={"content": [{"type": "text", "text": "Hi"}], "role": "assistant"})
        parsed = adapter.parse_response(resp)
        assert parsed.content == "Hi"

    def test_score(self, adapter):
        resp = httpx.Response(200, json={"content": [{"type": "text", "text": "Hi"}], "role": "assistant"})
        assert adapter.score(resp) >= 0.8


class TestGeminiAdapter:
    @pytest.fixture
    def adapter(self):
        from api_probe_system.core.adapters.base import GeminiAdapter
        return GeminiAdapter()

    def test_build_request(self, adapter):
        req = adapter.build_probe_request("Hello", "gemini-1.5-pro")
        assert req["contents"][0]["parts"][0]["text"] == "Hello"

    def test_parse_response(self, adapter):
        resp = httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": "Hi"}]}}]})
        parsed = adapter.parse_response(resp)
        assert parsed.content == "Hi"

    def test_score(self, adapter):
        resp = httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": "Hi"}]}}]})
        assert adapter.score(resp) >= 0.8


class TestOllamaAdapter:
    @pytest.fixture
    def adapter(self):
        from api_probe_system.core.adapters.base import OllamaAdapter
        return OllamaAdapter()

    def test_build_request(self, adapter):
        req = adapter.build_probe_request("Hello", "llama3")
        assert req["model"] == "llama3"

    def test_parse_response(self, adapter):
        resp = httpx.Response(200, json={"message": {"content": "Hi"}})
        parsed = adapter.parse_response(resp)
        assert parsed.content == "Hi"

    def test_score(self, adapter):
        resp = httpx.Response(200, json={"message": {"content": "Hi"}})
        assert adapter.score(resp) >= 0.8
