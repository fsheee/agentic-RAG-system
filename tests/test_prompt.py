from app.prompt import RAG_PROMPT


def _template():
    return RAG_PROMPT.messages[0].prompt.template


def test_prompt_includes_context_and_question():
    message = RAG_PROMPT.invoke(
        {
            "context": "Probation period is three months.",
            "input": "What is the probation period?",
        }
    )

    rendered = message.to_string()

    assert "Probation period is three months." in rendered
    assert "What is the probation period?" in rendered


def test_prompt_requires_answer_from_context_only():
    prompt_text = _template()

    assert "ONLY using the provided context" in prompt_text


def test_prompt_handles_empty_context_gracefully():
    message = RAG_PROMPT.invoke(
        {
            "context": "",
            "input": "What is the salary?",
        }
    )

    assert "What is the salary?" in message.to_string()


def test_prompt_tells_model_to_say_dont_know():
    prompt_text = _template()

    assert "I don't know based on the provided documents." in prompt_text