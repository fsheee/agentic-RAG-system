from app.llm import get_llm


def orchestrator(state) -> dict:
    question = state["question"]

    llm = get_llm()

    prompt = f"""
You are the orchestrator of a healthcare assistant.

Choose the correct agent for the user's question.

Available agents:
- rag: questions about hospital policies, HR policies, hospital information,
  visiting hours, rules, procedures, and documents.
- doctor: questions about doctors and doctor availability.
- booking: questions about booking, cancelling, or rescheduling appointments.

Return ONLY one word:
rag
doctor
booking

User question:
{question}
"""

    response = llm.invoke(prompt)

    content = response.content

    if isinstance(content, list):
        content = "".join(
            item.get("text", "")
            for item in content
            if isinstance(item, dict)
        )

    route = content.strip().lower()

    if route not in {"rag", "doctor", "booking"}:
        route = "rag"

    return {"route": route}