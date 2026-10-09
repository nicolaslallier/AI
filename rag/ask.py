import argparse

from rag.config import load_rag_config


def format_answer(question, out):
    lines = [f"Q : {question}", "", out["answer"].strip()]
    if out["cited"]:
        lines += ["", "Sources"]
        for n in out["cited"]:
            p = out["passages"][n - 1]
            score = f"{p['score']:.2f}".replace(".", ",")
            lines.append(f"  [{n}] {p['doc_id']} · caractères {p['start']}–{p['end']}    (score {score})")
    if out["invalid_citations"]:
        lines += ["", f"⚠ Citation invalide dans la réponse : {out['invalid_citations']} (numéro hors des passages fournis)."]
    return "\n".join(lines)


def main(argv):
    from rag.system import build

    ap = argparse.ArgumentParser(prog="rag.ask", description="Ask a question to the indexed documents.")
    ap.add_argument("config")
    ap.add_argument("question")
    args = ap.parse_args(argv)
    cfg = load_rag_config(args.config)
    print(format_answer(args.question, build(cfg)(args.question)))


if __name__ == "__main__":
    import sys

    main(sys.argv[1:])
