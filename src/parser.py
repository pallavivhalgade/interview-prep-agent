"""
Extracts plain text from an uploaded resume file (PDF or DOCX).

Kept separate from agent.py because file parsing is a distinct concern
from LLM orchestration - if we later support .txt or scanned PDFs (OCR),
only this file changes.
"""

import io
import pdfplumber
import docx

from src.logger import get_logger

logger = get_logger(__name__)


def extract_text_from_pdf(file_bytes: bytes) -> str:
    text_chunks = []
    with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
        for page in pdf.pages:
            page_text = page.extract_text()
            if page_text:
                text_chunks.append(page_text)
    logger.info(f"Extracted {len(text_chunks)} pages of text from PDF")
    return "\n".join(text_chunks)


def extract_text_from_docx(file_bytes: bytes) -> str:
    document = docx.Document(io.BytesIO(file_bytes))
    paragraphs = [p.text for p in document.paragraphs if p.text.strip()]
    logger.info(f"Extracted {len(paragraphs)} paragraphs from DOCX")
    return "\n".join(paragraphs)


def extract_resume_text(uploaded_file) -> str:
    """
    uploaded_file: a Streamlit UploadedFile object.
    Dispatches to the right extractor based on file extension.
    """
    filename = uploaded_file.name.lower()
    logger.info(f"Processing uploaded resume: {filename}")
    file_bytes = uploaded_file.read()

    if filename.endswith(".pdf"):
        return extract_text_from_pdf(file_bytes)
    elif filename.endswith(".docx"):
        return extract_text_from_docx(file_bytes)
    else:
        logger.warning(f"Unsupported file type uploaded: {filename}")
        raise ValueError("Unsupported file type. Please upload a PDF or DOCX file.")