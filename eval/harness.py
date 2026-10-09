from eval.metrics import answer_correct, source_hit


def evaluate(system, qa):
    results = []
    for row in qa:
        out = system(row["question"])
        if not isinstance(out, dict) or "answer" not in out or "sources" not in out:
            raise ValueError(
                f"system output for id {row['id']!r} must be a dict with 'answer' and 'sources'"
            )
        results.append(
            {
                "id": row["id"],
                "question": row["question"],
                "expected": row["answer"],
                "answer": out["answer"],
                "sources": out["sources"],
                "correct": answer_correct(out["answer"], row["answer"]),
                "source_hit": source_hit(out["sources"], row["sources"]) if row["sources"] else None,
            }
        )
    hits = [r["source_hit"] for r in results if r["source_hit"] is not None]
    metrics = {
        "n": len(results),
        "accuracy": sum(r["correct"] for r in results) / len(results) if results else 0.0,
        "recall_at_k": sum(hits) / len(hits) if hits else None,
    }
    return metrics, results
