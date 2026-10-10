def rrf(rankings, c=60):
    """Reciprocal Rank Fusion : score(id) = somme de 1 / (c + rang). Ne dépend pas de l'échelle des scores."""
    scores = {}
    for ranking in rankings:
        for rank, id_ in enumerate(ranking, 1):
            scores[id_] = scores.get(id_, 0.0) + 1.0 / (c + rank)
    return sorted(scores.items(), key=lambda kv: -kv[1])  # tri stable : égalité = ordre d'apparition


class CrossEncoderReranker:
    def __init__(self, model):
        from sentence_transformers import CrossEncoder

        self._model = CrossEncoder(model)

    def score(self, query, texts):
        return [float(s) for s in self._model.predict([(query, t) for t in texts], show_progress_bar=False)]


class Retriever:
    """dense | hybrid (dense + FTS par RRF), puis reranking optionnel des `candidates` premiers → top-k."""

    def __init__(self, index, embedder, mode, k, candidates, reranker=None):
        self.index, self.embedder, self.mode = index, embedder, mode
        self.k, self.candidates, self.reranker = k, candidates, reranker

    def __call__(self, query):
        n = self.candidates if (self.mode == "hybrid" or self.reranker) else self.k
        passages = self.index.search(self.embedder.embed_query(query), n)
        if self.mode == "hybrid":
            lexical = self.index.search_text(query, n)  # [] si requête vide / mots vides → retombe sur le dense
            by_id = {p["id"]: p for p in lexical} | {p["id"]: p for p in passages}
            passages = [
                {**by_id[i], "score": s} for i, s in rrf([[p["id"] for p in passages], [p["id"] for p in lexical]])
            ]
            passages = passages[:n]  # l'union dense+lexical peut dépasser `candidates` : plafonne le pool du reranker
        if self.reranker:
            scores = self.reranker.score(query, [p["text"] for p in passages])
            passages = sorted(({**p, "score": s} for p, s in zip(passages, scores)), key=lambda p: -p["score"])
        return passages[: self.k]


def make_retriever(settings, index, embedder):
    r = settings["retrieval"]
    reranker = CrossEncoderReranker(r["rerank"]) if r["rerank"] else None
    return Retriever(index, embedder, r["mode"], r["k"], r["candidates"], reranker)
