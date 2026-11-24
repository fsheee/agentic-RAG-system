from app import llm


def test_uses_gemini_when_google_api_key_is_set(monkeypatch):
    captured = {}

    monkeypatch.setattr(llm, "GOOGLE_API_KEY", "google-key")
    monkeypatch.setattr(llm, "GROQ_API_KEY", None)
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
    monkeypatch.setattr(llm, "MODEL_NAME", "openai/gpt-oss-120b")
    monkeypatch.setattr(llm, "ChatGoogleGenerativeAI", lambda **kwargs: "gemini_llm")
    monkeypatch.setattr(llm, "ChatGroq", lambda **kwargs: "groq_llm")

    result = llm.get_llm()

    # Gemini stays the primary; Groq is only the safety net.
    assert isinstance(result, llm.FallbackLLM)
    assert result.primary == "gemini_llm"
    assert result.fallback == "groq_llm"


def test_falls_back_when_primary_raises():
    class Boom:
        def invoke(self, input, *args, **kwargs):
            raise RuntimeError("503 UNAVAILABLE")

    class Answer:
        def invoke(self, input, *args, **kwargs):
            return f"fallback:{input}"

    result = llm.FallbackLLM(Boom(), Answer()).invoke("question")

    assert result == "fallback:question"


def test_uses_primary_when_it_succeeds():
    class Answer:
        def __init__(self, text):
            self.text = text

        def invoke(self, input, *args, **kwargs):
            return self.text

    class MustNotBeCalled:
        def invoke(self, input, *args, **kwargs):
            raise AssertionError("fallback should not run")

    result = llm.FallbackLLM(Answer("primary"), MustNotBeCalled()).invoke("q")

    assert result == "primary"
