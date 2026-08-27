from app.agent.orchestrator import orchestrator


questions = [
    "How many annual leave days are employees allowed?",
    "Which doctors are available?",
    "I want to book an appointment.",
]

for question in questions:
    result = orchestrator({"question": question})
    print(f"Question: {question}")
    print(f"Route: {result['route']}")
    print()