class SentenceTransformerEmbedder:
    """Le préfixe (E5 : "query: " / "passage: ") est un paramètre de config, pas de la logique."""

    def __init__(self, model, batch_size, query_prefix, passage_prefix):
        from sentence_transformers import SentenceTransformer

        self._model = SentenceTransformer(model)
        self._batch_size = batch_size
        self._qp, self._pp = query_prefix, passage_prefix

    def _encode(self, texts):
        return self._model.encode(
            texts, batch_size=self._batch_size, normalize_embeddings=True, show_progress_bar=False
        ).tolist()

    def embed_documents(self, texts):
        return self._encode([self._pp + t for t in texts])

    def embed_query(self, text):
        return self._encode([self._qp + text])[0]


def make_embedder(settings):
    e = settings["embedding"]
    return SentenceTransformerEmbedder(e["model"], e["batch_size"], e["query_prefix"], e["passage_prefix"])
