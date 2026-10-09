import unicodedata


def normalize(s):
    s = unicodedata.normalize("NFKD", str(s).casefold())
    s = "".join(c for c in s if not unicodedata.combining(c))
    return " ".join(s.split())


def answer_correct(pred, expected):
    return normalize(expected) in normalize(pred)


def source_hit(pred_sources, expected_sources):
    return bool(set(pred_sources) & set(expected_sources))
