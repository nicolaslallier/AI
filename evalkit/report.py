import textwrap

DASH = "—"
WIDTH = 80


def fmt_rate(correct, n):
    return f"{correct / n:.2f} ({correct}/{n})".replace(".", ",") if n else DASH


def _ratio(v):
    return DASH if v is None else f"{v:.2f}".replace(".", ",")


def _seconds(v):
    return DASH if v is None else f"{v:.1f} s".replace(".", ",")


def _correct(m):
    return round(m["accuracy"] * m["n"])


def _verdict(metrics, min_gap):
    names = list(metrics)
    if len(names) < 2:
        return "Un seul système évalué : pas de comparaison."
    ref, parts = names[0], []
    for name in names[1:]:
        gap = _correct(metrics[name]) - _correct(metrics[ref])
        pts = round(100 * (metrics[name]["accuracy"] - metrics[ref]["accuracy"]))
        tail = " (écart non concluant)" if abs(gap) < min_gap else ""
        parts.append(f"{name} {pts:+d} points ({gap:+d} question(s)){tail}")
    n = metrics[ref]["n"]
    return f"Exactitude par rapport à `{ref}` sur {n} questions : " + " ; ".join(parts) + "."


def _clip(text, width):
    text = " ".join(str(text).split())
    return text if len(text) <= width else text[: width - 1] + "…"


def _bullet(text):
    return textwrap.fill(text, width=WIDTH, subsequent_indent="  ",
                         break_on_hyphens=False)


def _check(metrics, results):
    if not results:
        raise ValueError("results is empty: nothing to report")
    if set(metrics) != set(results):
        raise ValueError("metrics and results must have the same systems")
    lengths = {len(rows) for rows in results.values()}
    if len(lengths) > 1:
        raise ValueError("all systems must have the same number of rows")
    ns = {m["n"] for m in metrics.values()}
    if len(ns) > 1:
        raise ValueError("all systems must share the same n")


def _divergent(results, limit=3):
    names = list(results)
    scored = []
    for i in range(len(results[names[0]])):
        ok = [results[n][i]["correct"] for n in names]
        if 0 < sum(ok) < len(ok):
            scored.append((abs(sum(ok) - len(ok) / 2), i))  # plus proche d'un partage moitié/moitié d'abord
    return [i for _, i in sorted(scored)[:limit]]


def render_report(name, command, metrics, results, latency, min_gap, warnings=(), notes=()):
    _check(metrics, results)
    out = [textwrap.fill(f"# Comparaison — {name}", width=WIDTH, break_on_hyphens=False), ""]
    out += [textwrap.fill(w, width=WIDTH, initial_indent="> ⚠ ", subsequent_indent="> ",
                          break_on_hyphens=False) for w in warnings]
    out += [""] if warnings else []
    out += ["## Verdict", "", textwrap.fill(_verdict(metrics, min_gap), width=WIDTH,
                                            break_on_hyphens=False), ""]
    out += ["## Tableau", "", "| Système | Exactitude | Recall@k | Fidélité | Latence |", "|---|---|---|---|---|"]
    for n, m in metrics.items():
        out.append(
            f"| {n} | {fmt_rate(_correct(m), m['n'])} | {_ratio(m.get('recall_at_k'))} "
            f"| {_ratio(m.get('citation_validity'))} | {_seconds(latency.get(n))} |"
        )
    out += ["", "## Cas parlants", ""]
    picks = _divergent(results)
    if not picks:
        out.append("Aucune divergence : tous les systèmes ont le même verdict sur chaque question.")
    for i in picks:
        first = results[next(iter(results))][i]
        qid = first["id"]
        expected = _clip(first["expected"], 20)
        question = _clip(first["question"], max(10, WIDTH - 22 - len(qid) - len(expected)))
        out += [f"**{qid} — {question}** (attendu : `{expected}`)", ""]
        for n in results:
            mark = "✔" if results[n][i]["correct"] else "✘"
            budget = WIDTH - len(f"- {n} {mark} : ") - 2  # 2 : guillemets du repr
            out.append(f"- {n} {mark} : {_clip(results[n][i]['answer'], budget)!r}")
        out.append("")
    limits = [
        "- Verdict fondé sur des **règles** (la réponse attendue figure dans la réponse), pas sur un LLM juge ; "
        "relire à la main un échantillon de `outputs.jsonl`.",
        "- Les systèmes `+rag` utilisent le prompt RAG (passages numérotés + citations) ; `system_prompt` ne "
        "s'applique qu'aux systèmes sans RAG.",
        f"- Un écart inférieur à {min_gap} question(s) n'est pas interprétable à cet effectif.",
        *[f"- {n}" for n in notes],
    ]
    out += ["## Limites", ""]
    out += [_bullet(b) for b in limits]
    out += [
        "",
        "## Reproduire",
        "",
        f"```bash\n{command}\n```",
        "",
    ]
    return "\n".join(out)
