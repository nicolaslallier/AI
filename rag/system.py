from rag.config import rag_settings
from rag.generate import build_messages, parse_citations
from rag.index import open_index
from rag.ingest import load_documents


def make_embedder(settings):
    from rag.embed import make_embedder as make

    return make(settings)


def make_generator(settings):
    from common.llm import Generator

    return Generator(settings["generation"]["model"])


class RagSystem:
    def __init__(self, index, embedder, generator, k, max_tokens, temperature):
        self.index, self.embedder, self.generator = index, embedder, generator
        self.k, self.max_tokens, self.temperature = k, max_tokens, temperature

    def __call__(self, question):
        passages = self.index.search(self.embedder.embed_query(question), self.k)
        text = self.generator.generate(
            build_messages(question, passages), max_tokens=self.max_tokens, temperature=self.temperature
        )
        cited, total, invalid = parse_citations(text, len(passages))
        sources = []
        for n in cited:
            if passages[n - 1]["doc_id"] not in sources:
                sources.append(passages[n - 1]["doc_id"])
        return {
            "answer": text,
            "sources": sources,
            "retrieved": [p["doc_id"] for p in passages],
            "citations": total,
            "invalid_citations": invalid,
            "passages": passages,
            "cited": cited,
        }


def build(cfg):
    s = rag_settings(cfg)
    index = open_index(s, load_documents(s["docs_dir"]))  # échoue tôt si l'index est périmé
    g = s["generation"]
    # Les deux modèles sont chargés ensemble : OK pour un 3B 4 bits + bge-m3 sur 24 Go (TRD §3),
    # à mesurer avant de monter en taille.
    return RagSystem(index, make_embedder(s), make_generator(s), s["retrieval"]["k"], g["max_tokens"], g["temperature"])
