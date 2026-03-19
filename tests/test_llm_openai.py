from unittest.mock import MagicMock, patch
from showrunner.providers.llm.openai import OpenAILLMProvider
from showrunner.providers.llm.base import LLMProvider


def test_openai_is_llm_provider():
    assert issubclass(OpenAILLMProvider, LLMProvider)


@patch("showrunner.providers.llm.openai.openai")
def test_generate(mock_mod):
    mock_client = MagicMock()
    mock_mod.OpenAI.return_value = mock_client
    mock_client.chat.completions.create.return_value = MagicMock(
        choices=[MagicMock(message=MagicMock(content="Hello world"))]
    )
    provider = OpenAILLMProvider(model="gpt-4o")
    result = provider.generate(system="Be helpful", prompt="Say hello")
    assert result == "Hello world"


@patch("showrunner.providers.llm.openai.openai")
def test_generate_json(mock_mod):
    mock_client = MagicMock()
    mock_mod.OpenAI.return_value = mock_client
    mock_client.chat.completions.create.return_value = MagicMock(
        choices=[MagicMock(message=MagicMock(content='{"key": "value"}'))]
    )
    provider = OpenAILLMProvider()
    result = provider.generate_json(system="Return JSON", prompt="Data")
    assert result == {"key": "value"}
