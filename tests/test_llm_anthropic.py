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


@patch("showrunner.providers.llm.anthropic.anthropic")
def test_usage_tracking_accumulates_tokens(mock_mod):
    mock_client = MagicMock()
    mock_mod.Anthropic.return_value = mock_client
    mock_client.messages.create.return_value = MagicMock(
        content=[MagicMock(text="hi")],
        usage=MagicMock(input_tokens=100, output_tokens=40),
    )
    provider = AnthropicLLMProvider()
    provider.generate(system="s", prompt="p")
    provider.generate(system="s", prompt="p")
    assert provider.get_usage() == {"input_tokens": 200, "output_tokens": 80, "calls": 2}


@patch("showrunner.providers.llm.anthropic.anthropic")
def test_usage_tracking_tolerates_missing_usage(mock_mod):
    """Responses without real token counts (e.g. bare mocks) still count
    the call and never crash."""
    mock_client = MagicMock()
    mock_mod.Anthropic.return_value = mock_client
    mock_client.messages.create.return_value = MagicMock(content=[MagicMock(text="hi")])
    provider = AnthropicLLMProvider()
    provider.generate(system="s", prompt="p")
    assert provider.get_usage() == {"input_tokens": 0, "output_tokens": 0, "calls": 1}
