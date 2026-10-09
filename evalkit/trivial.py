from common.jsonl import read_qa


def build(cfg):
    table = {}
    for r in read_qa(cfg["eval_set"]):
        if r["question"] in table:
            raise ValueError(f"trivial system: duplicate question {r['question']!r}")
        table[r["question"]] = {"answer": r["answer"], "sources": r["sources"]}

    def answer(question):
        if question not in table:
            raise ValueError(f"trivial system: unknown question {question!r}")
        return table[question]

    return answer
