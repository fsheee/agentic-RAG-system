from langgraph.graph import StateGraph, START, END

from app.agent.state import AgentState
from app.retriever import retrieve_documents
from app.llm import get_llm
from app.prompt import RAG_PROMPT


def retrieve_node(state: AgentState):
    documents = retrieve_documents(state["question"])

    context = "\n\n".join(
        document.page_content
        for document in documents
    )

    return {
        "documents": documents,
        "context": context,
    }


def generate_node(state: AgentState):
    prompt = RAG_PROMPT.format(
        context=state["context"],
        input=state["question"],
    )

    llm = get_llm()
    response = llm.invoke(prompt)

    return {
        "answer": response.content,
    }


builder = StateGraph(AgentState)

builder.add_node("retrieve", retrieve_node)
builder.add_node("generate", generate_node)

builder.add_edge(START, "retrieve")
builder.add_edge("retrieve", "generate")
builder.add_edge("generate", END)

graph = builder.compile()



if __name__ == "__main__":
    print(graph.get_graph().draw_ascii())