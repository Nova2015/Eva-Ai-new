"""
OCR Indexer — Converts PDF pages OR images to text, stores chunks in FAISS.
"""
import os
import pytesseract
from PIL import Image
from pdf2image import convert_from_path
from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_community.vectorstores import FAISS
from dotenv import load_dotenv

load_dotenv(dotenv_path=os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env"))

pytesseract.pytesseract.tesseract_cmd = r"D:\\Tesseract\\tesseract.exe"

BASE_DIR       = os.path.dirname(os.path.dirname(__file__))
DATA_DIR       = os.path.join(BASE_DIR, "data")
FAISS_INDEX_PATH = os.path.join(BASE_DIR, "faiss_index")
EMBEDDINGS_MODEL = "all-MiniLM-L6-v2"

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".bmp", ".tiff", ".webp"}
PDF_EXTENSIONS   = {".pdf"}

def ocr_and_index(filename: str):
    filepath = os.path.join(DATA_DIR, filename)
    if not os.path.exists(filepath):
        raise FileNotFoundError(f"File not found: {filepath}")

    ext = os.path.splitext(filename)[1].lower()
    texts = []

    if ext in IMAGE_EXTENSIONS:
        print(f"[IMAGE] Processing image: {filepath}")
        img = Image.open(filepath)
        text = pytesseract.image_to_string(img)
        if text.strip():
            texts.append({"text": text, "page": 1})
        else:
            print("[IMAGE] No text found in image.")

    elif ext in PDF_EXTENSIONS:
        print(f"[PDF] Converting PDF: {filepath}")
        images = convert_from_path(
            filepath,
            poppler_path=r"E:\code\Rag project\poppler\Library\bin"
        )
        print(f"[PDF] Total pages: {len(images)}")
        for i, img in enumerate(images):
            text = pytesseract.image_to_string(img)
            if text.strip():
                texts.append({"text": text, "page": i + 1})
        print(f"[PDF] Pages with text: {len(texts)}")

    else:
        # Plain text files
        with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
            text = f.read()
        if text.strip():
            texts.append({"text": text, "page": 1})

    if not texts:
        print("No text extracted.")
        return

    # Split into chunks
    splitter = RecursiveCharacterTextSplitter(chunk_size=500, chunk_overlap=50)
    docs = []
    for item in texts:
        chunks = splitter.create_documents([item["text"]])
        for chunk in chunks:
            chunk.metadata["page"] = item["page"]
            chunk.metadata["source"] = filename
        docs.extend(chunks)

    print(f"[CHUNKS] Total chunks: {len(docs)}")

    # Save to FAISS
    embeddings = HuggingFaceEmbeddings(model_name=EMBEDDINGS_MODEL)
    if os.path.exists(FAISS_INDEX_PATH):
        vectorstore = FAISS.load_local(
            FAISS_INDEX_PATH, embeddings,
            allow_dangerous_deserialization=True
        )
        vectorstore.add_documents(docs)
    else:
        vectorstore = FAISS.from_documents(docs, embeddings)

    vectorstore.save_local(FAISS_INDEX_PATH)
    print(f"[DONE] FAISS index saved: {FAISS_INDEX_PATH}")


if __name__ == "__main__":
    ocr_and_index("sample.pdf")

