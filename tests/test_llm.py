from app import llm


def test_uses_gemini_when_google_api_key_is_set(monkeypatch):
    captured = {}

    monkeypatch.setattr(llm, "GOOGLE_API_KEY", "google-key")
    monkeypatch.setattr(
        llm,
        "ChatGoogleGenerativeAI",
        lambda **kwargs: captured.update(kwargs) or "gemini_llm",
    )

    result = llm.get_llm()

    assert result == "gemini_llm"
    assert captured["api_key"] == "google-key"
    assert captured["temperature"] == 0


def test_uses_groq_when_no_google_api_key(monkeypatch):
    captured = {}

    monkeypatch.setattr(llm, "GOOGLE_API_KEY", None)
    monkeypatch.setattr(llm, "GROQ_API_KEY", "groq-key")
    monkeypatch.setattr(llm, "MODEL_NAME", "openai/gpt-oss-120b")
    monkeypatch.setattr(
        llm,
        "ChatGroq",
        lambda **kwargs: captured.update(kwargs) or "groq_llm",
    )

    result = llm.get_llm()

    assert result == "groq_llm"
    assert captured["api_key"] == "groq-key"
    assert captured["model"] == "openai/gpt-oss-120b"


def test_prefers_gemini_even_when_groq_key_exists(monkeypatch):
    monkeypatch.setattr(llm, "GOOGLE_API_KEY", "google-key")
    monkeypatch.setattr(llm, "GROQ_API_KEY", "groq-key")
    monkeypatch.setattr(llm, "ChatGoogleGenerativeAI", lambda **kwargs: "gemini_llm")

    assert llm.get_llm() == "gemini_llm"