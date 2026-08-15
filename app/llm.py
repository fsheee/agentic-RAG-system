import os

from dotenv import load_dotenv
from langchain_groq import ChatGroq


load_dotenv()


def get_llm():
    return ChatGroq(
        model=os.getenv("MODEL_NAME"),
        api_key=os.getenv("GROQ_API_KEY"),
        temperature=0,
    )
# if __name__ == "__main__":
#     llm = get_llm()
#     response = llm.invoke("Say hello in one sentence.")
#     print(response.content)

