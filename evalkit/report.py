DASH = "—"


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


def _divergent(results, limit=3):
    names = list(results)
    scored = []
    for i, base_row in enumerate(results[names[0]]):
        ok = [results[n][i]["correct"] for n in names]
        if 0 < sum(ok) < len(ok):
            scored.append((abs(sum(ok) - len(ok) / 2), i))  # plus proche d'un partage moitié/moitié d'abord
    return [i for _, i in sorted(scored)[:limit]]


def render_report(name, command, metrics, results, latency, min_gap, warnings=(), notes=()):
    out = [f"# Comparaison — {name}", ""]
    out += [f"> ⚠ {w}" for w in warnings] + ([""] if warnings else [])
    out += ["## Verdict", "", _verdict(metrics, min_gap), ""]
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
        out += [f"**{first['id']} — {first['question']}** (attendu : `{first['expected']}`)", ""]
        out += [f"- {n} {'✔' if results[n][i]['correct'] else '✘'} : {results[n][i]['answer']!r}" for n in results]
        out.append("")
    out += ["## Limites", ""]
    out += [
        "- Verdict fondé sur des **règles** (la réponse attendue figure dans la réponse), pas sur un LLM juge ; "
        "relire à la main un échantillon de `outputs.jsonl`.",
        "- Les systèmes `+rag` utilisent le prompt RAG (passages numérotés + citations) ; `system_prompt` ne "
        "s'applique qu'aux systèmes sans RAG.",
        f"- Un écart inférieur à {min_gap} question(s) n'est pas interprétable à cet effectif.",
        *[f"- {n}" for n in notes],
        "",
        "## Reproduire",
        "",
        f"```bash\n{command}\n```",
        "",
    ]
    return "\n".join(out)
