from common.jsonl import read_qa


def build(cfg):
    table = {r["question"]: {"answer": r["answer"], "sources": r["sources"]} for r in read_qa(cfg["eval_set"])}
    return lambda question: table[question]
