# (séparateur, nombre de caractères gardés dans le chunk courant) du plus fort au plus faible.
# Un titre "## " est coupé *avant* lui, pour ouvrir le chunk suivant.
SEPARATORS = (("\n## ", 1), ("\n\n", 2), ("\n", 1), (". ", 2), (" ", 1))


# ponytail: une seule passe par fenêtre au lieu d'un découpage récursif complet ;
# passer à un vrai récursif si les coupes tombent mal sur des documents réels.
def split_spans(text, size, overlap):
    if not 0 <= overlap < size:
        raise ValueError("need 0 <= overlap < size")
    spans, start = [], 0
    while start < len(text):
        end = min(start + size, len(text))
        if end < len(text):
            window = text[start:end]
            for sep, keep in SEPARATORS:
                i = window.rfind(sep, size // 2)
                if i != -1:
                    end = start + i + keep
                    break
        spans.append((start, end))
        if end >= len(text):
            break
        start = max(end - overlap, start + 1)
    return spans


def chunk_document(doc_id, text, size, overlap):
    chunks = []
    for start, end in split_spans(text, size, overlap):
        piece = text[start:end]
        if piece.strip():
            chunks.append(
                {"id": f"{doc_id}#{len(chunks)}", "doc_id": doc_id, "text": piece, "start": start, "end": end}
            )
    return chunks
