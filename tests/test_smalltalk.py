from app.smalltalk import is_greeting


def test_plain_greetings_are_recognised():
    for text in [
        "hi",
        "Hi!",
        "hello",
        "Hello?",
        "hey there",
        "yo",
        "hiya",
        "Good morning",
        "good evening!",
        "greetings",
        "salam",
        "salaam",
        "assalam o alaikum",
        "Assalamu Alaikum",
        "hello again",
        "hi team",
    ]:
        assert is_greeting(text), text


def test_greeting_with_a_real_question_is_not_a_greeting():
    for text in [
        "hi, what are the visiting hours?",
        "hello can I book an appointment",
        "hey show my appointments",
        "hi how much is the consultation fee",
        "good morning, any cardiologist available?",
    ]:
        assert not is_greeting(text), text


def test_non_greetings_are_not_matched():
    for text in ["", None, "what are the visiting hours?", "thanks", "book a doctor"]:
        assert not is_greeting(text), text
