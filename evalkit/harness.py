from evalkit.metrics import answer_correct, source_hit


def _is_count(v):
    return isinstance(v, int) and not isinstance(v, bool) and v >= 0


def evaluate(system, qa):
    results = []
    for row in qa:
        out = system(row["question"])
        if not isinstance(out, dict) or "answer" not in out or "sources" not in out:
            raise ValueError(
                f"system output for id {row['id']!r} must be a dict with 'answer' and 'sources'"
            )
        if not isinstance(out["sources"], list) or not all(isinstance(s, str) for s in out["sources"]):
            raise ValueError(f"system output for id {row['id']!r}: 'sources' must be a list of strings")
        if "retrieved" in out and (
            not isinstance(out["retrieved"], list) or not all(isinstance(s, str) for s in out["retrieved"])
        ):
            raise ValueError(f"system output for id {row['id']!r}: 'retrieved' must be a list of strings")
        for key in ("citations", "invalid_citations"):
            if key in out and not _is_count(out[key]):
                raise ValueError(f"system output for id {row['id']!r}: {key!r} must be a non-negative integer")
        result = {
            "id": row["id"],
            "question": row["question"],
            "expected": row["answer"],
            "answer": out["answer"],
            "sources": out["sources"],
            "correct": answer_correct(out["answer"], row["answer"]),
            "source_hit": source_hit(out["sources"], row["sources"]) if row["sources"] else None,
        }
        if "retrieved" in out:
            result["retrieval_hit"] = source_hit(out["retrieved"], row["sources"]) if row["sources"] else None
        for key in ("citations", "invalid_citations"):
            if key in out:
                result[key] = out[key]
        results.append(result)
    hits = [r["source_hit"] for r in results if r["source_hit"] is not None]
    metrics = {
        "n": len(results),
        "accuracy": sum(r["correct"] for r in results) / len(results) if results else 0.0,
        "source_hit_rate": sum(hits) / len(hits) if hits else None,
    }
    if any("retrieval_hit" in r for r in results):
        rh = [r["retrieval_hit"] for r in results if r.get("retrieval_hit") is not None]
        metrics["recall_at_k"] = sum(rh) / len(rh) if rh else None
    if any("citations" in r for r in results):
        total = sum(r.get("citations", 0) for r in results)
        invalid = sum(r.get("invalid_citations", 0) for r in results)
        metrics["citation_validity"] = 1 - invalid / total if total else None
    return metrics, results
