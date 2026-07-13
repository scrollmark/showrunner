def test_public_imports():
    from showrunner import __version__, Pipeline, Plan, Format, Feedback

    assert __version__ == "0.2.0"
    assert Pipeline is not None
    assert Plan is not None
    assert Format is not None
    assert Feedback is not None


def test_provider_imports():
    from showrunner.providers.llm.base import LLMProvider

    assert LLMProvider is not None


def test_style_imports():
    from showrunner.styles.resolver import resolve_style, list_presets

    assert callable(resolve_style)
    assert callable(list_presets)
