from unittest.mock import MagicMock, patch
from showrunner.providers.llm.anthropic import AnthropicLLMProvider
from showrunner.providers.llm.base import LLMProvider


def test_anthropic_is_llm_provider():
    assert issubclass(AnthropicLLMProvider, LLMProvider)


@patch("showrunner.providers.llm.anthropic.anthropic")
def test_generate(mock_mod):
    mock_client = MagicMock()
    mock_mod.Anthropic.return_value = mock_client
    mock_client.messages.create.return_value = MagicMock(content=[MagicMock(text="Hello world")])
    provider = AnthropicLLMProvider(model="claude-sonnet-4-5-20250929")
    result = provider.generate(system="Be helpful", prompt="Say hello")
    assert result == "Hello world"


@patch("showrunner.providers.llm.anthropic.anthropic")
def test_generate_json(mock_mod):
    mock_client = MagicMock()
    mock_mod.Anthropic.return_value = mock_client
    mock_client.messages.create.return_value = MagicMock(content=[MagicMock(text='{"key": "value"}')])
    provider = AnthropicLLMProvider()
    result = provider.generate_json(system="Return JSON", prompt="Data")
    assert result == {"key": "value"}


@patch("showrunner.providers.llm.anthropic.anthropic")
def test_generate_json_strips_markdown_fence(mock_mod):
    mock_client = MagicMock()
    mock_mod.Anthropic.return_value = mock_client
    mock_client.messages.create.return_value = MagicMock(content=[MagicMock(text='```json\n{"key": "value"}\n```')])
    provider = AnthropicLLMProvider()
    result = provider.generate_json(system="Return JSON", prompt="Data")
    assert result == {"key": "value"}
