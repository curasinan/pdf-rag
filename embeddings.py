from sentence_transformers import SentenceTransformer
from config import EMBEDDING_MODEL, EMBED_BATCH_SIZE, EMBED_MAX_LENGTH

_model = None


def get_model() -> SentenceTransformer:
    """Lazy-load the BGE-M3 model. ~2.3GB download on first run."""
    global _model
    if _model is None:
        _model = SentenceTransformer(EMBEDDING_MODEL, trust_remote_code=True)
        # Cap max sequence length to keep encoding fast on long chunks
        if hasattr(_model, "max_seq_length"):
            _model.max_seq_length = EMBED_MAX_LENGTH
    return _model


def embed_texts(texts: list[str]) -> list[list[float]]:
    """Embed a list of texts with BGE-M3. Vectors are L2-normalized so cosine == dot product."""
    model = get_model()
    embeddings = model.encode(
        texts,
        batch_size=EMBED_BATCH_SIZE,
        normalize_embeddings=True,
        show_progress_bar=len(texts) > 20,
        convert_to_numpy=True,
    )
    return embeddings.tolist()
