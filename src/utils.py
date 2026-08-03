"""
Utility functions - currently focused on Resume <-> JD similarity matching
using local sentence embeddings (no external API needed for this part).
"""

from sentence_transformers import SentenceTransformer
from sklearn.metrics.pairwise import cosine_similarity

EMBEDDING_MODEL = "all-MiniLM-L6-v2"  # small, fast, runs locally

_model = None  # lazy-loaded singleton so the model loads once, not per call


def _get_embedding_model():
    global _model
    if _model is None:
        _model = SentenceTransformer(EMBEDDING_MODEL)
    return _model


def compute_match_score(resume_text: str, job_description: str) -> float:
    """
    Returns a 0-100 similarity score between resume and job description,
    based on cosine similarity of their sentence embeddings.
    """
    model = _get_embedding_model()

    embeddings = model.encode([resume_text, job_description])
    similarity = cosine_similarity([embeddings[0]], [embeddings[1]])[0][0]

    return round(float(similarity) * 100, 1)
