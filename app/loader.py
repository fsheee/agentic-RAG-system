from pypdf import PdfReader


def load_pdf(file_path: str) -> str:
    reader = PdfReader(file_path)

    text = ""

    for page in reader.pages:
        text += page.extract_text() or ""

    return text

if __name__ == "__main__":
     text = load_pdf("knowledge_base/hospital_info.pdf")
print(text)

