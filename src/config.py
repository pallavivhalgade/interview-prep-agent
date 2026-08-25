"""
Central configuration for the Interview Prep Agent.

Keeping constants here means changing a model name or threshold
happens in one place, not scattered across the codebase.
"""

import os
from dotenv import load_dotenv

load_dotenv()

# --- API ---
GROQ_API_KEY = os.environ.get("GROQ_API_KEY")
LLM_MODEL = "openai/gpt-oss-20b"
LLM_TEMPERATURE = 0.4

# --- Embeddings (for Resume <-> JD matching) ---
EMBEDDING_MODEL = "all-MiniLM-L6-v2"  # small, fast, runs locally via sentence-transformers

# --- File upload ---
ALLOWED_RESUME_EXTENSIONS = [".pdf", ".docx"]
MAX_RESUME_SIZE_MB = 5

# --- Logging ---
LOG_LEVEL = "INFO"
LOG_FILE = "app.log"
