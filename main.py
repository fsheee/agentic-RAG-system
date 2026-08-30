from app.core import ask


def main():
    question = input("Ask a question: ")

    result = ask(question)

    print("\nAnswer:")
    print(result["answer"])

    if result["sources"]:
        print("\nSources:")
        for source in result["sources"]:
            page = f" — page {source['page']}" if source["page"] is not None else ""
            print(f"- {source['source']}{page}")


if __name__ == "__main__":
    main()
