from app.rag_chain import generate_answer
import app.config



def main():
    question = input("Ask a question: ")

    answer = generate_answer(question)

    print("\nAnswer:")
    print(answer)


if __name__ == "__main__":
    main()