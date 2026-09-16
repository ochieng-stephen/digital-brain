"""Local, LLM-free embeddings via fastembed (ONNX, no API key).

The brain owns only this *retrieval* model — never a reasoning model. See
design/thought-cycle-protocol.md ("The brain never owns a reasoning model").
"""
from __future__ import annotations

import numpy as np

from .config import EMBED_MODEL

_model = None


def _get_model():
    global _model
    if _model is None:
        from fastembed import TextEmbedding  # lazy: first call downloads the model
        _model = TextEmbedding(model_name=EMBED_MODEL)
    return _model


def embed(text: str) -> np.ndarray:
    """Return a float32 embedding vector for a single string."""
    vec = next(_get_model().embed([text]))
    return np.asarray(vec, dtype=np.float32)
