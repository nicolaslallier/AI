import re

NOT_FOUND = "Je n'ai pas trouvé d'information dans les documents indexés."

SYSTEM = (
    "Tu réponds uniquement à partir des passages numérotés fournis. "
    "Cite chaque affirmation avec le numéro de son passage entre crochets, par exemple [1]. "
    f"Si les passages ne contiennent pas l'information, réponds exactement : {NOT_FOUND}"
)

_CITATION = re.compile(r"\[(\d+(?:\s*,\s*\d+)*)\]")


def build_messages(question, chunks):
    context = "\n\n".join(f"[{i}] ({c['doc_id']})\n{c['text']}" for i, c in enumerate(chunks, 1))
    return [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": f"Passages :\n{context}\n\nQuestion : {question}"},
    ]


def parse_citations(text, n_passages):
    cited, total, invalid = [], 0, 0
    for group in _CITATION.findall(text):
        for num in (int(x) for x in group.split(",")):
            total += 1
            if 1 <= num <= n_passages:
                if num not in cited:
                    cited.append(num)
            else:
                invalid += 1
    return cited, total, invalid
