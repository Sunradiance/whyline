import math
import re
from collections import Counter


def _tokenize(text: str) -> list[str]:
    return re.findall(r'[a-z0-9]{3,}', (text or '').lower())


def score_decisions(question: str, decisions: list[dict], top_k: int = 8) -> list[dict]:
    """BM25-lite keyword retrieval — no extra API calls."""
    if not decisions:
        return []
    q_tokens = _tokenize(question)
    if not q_tokens:
        return decisions[:top_k]

    q_counts = Counter(q_tokens)
    docs = []
    for d in decisions:
        blob = ' '.join([
            d.get('title', ''), d.get('summary', ''), d.get('reasoning', ''),
            d.get('decidedBy', ''), ' '.join(
                a.get('option', '') + ' ' + a.get('whyRejected', '')
                for a in (d.get('alternativesConsidered') or [])
            ),
        ])
        tokens = _tokenize(blob)
        tf = Counter(tokens)
        docs.append((d, tf, len(tokens) or 1))

    avg_dl = sum(dl for _, _, dl in docs) / len(docs)
    scored = []
    k1, b = 1.2, 0.75
    N = len(docs)

    df = Counter()
    for tok in set(q_tokens):
        df[tok] = sum(1 for _, tf, _ in docs if tok in tf)

    for d, tf, dl in docs:
        s = 0.0
        for tok, qf in q_counts.items():
            if tok not in tf:
                continue
            n_qi = df.get(tok, 0)
            idf = math.log((N - n_qi + 0.5) / (n_qi + 0.5) + 1)
            f = tf[tok]
            denom = f + k1 * (1 - b + b * dl / avg_dl)
            s += idf * (f * (k1 + 1)) / (denom or 1)
        scored.append((s, d))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [d for s, d in scored[:top_k] if s > 0]


def best_match_score(query: str, decisions: list[dict]) -> tuple[float, dict | None]:
    """Top BM25 score + decision — for near-dup detection on ingest."""
    if not decisions or not query.strip():
        return 0.0, None
    q_tokens = _tokenize(query)
    if not q_tokens:
        return 0.0, None
    q_counts = Counter(q_tokens)
    docs = []
    for d in decisions:
        blob = ' '.join([d.get('title', ''), d.get('summary', ''), d.get('reasoning', '')])
        tokens = _tokenize(blob)
        tf = Counter(tokens)
        docs.append((d, tf, len(tokens) or 1))
    avg_dl = sum(dl for _, _, dl in docs) / len(docs)
    k1, b = 1.2, 0.75
    N = len(docs)
    df = Counter()
    for tok in set(q_tokens):
        df[tok] = sum(1 for _, tf, _ in docs if tok in tf)
    best_s, best_d = 0.0, None
    for d, tf, dl in docs:
        s = 0.0
        for tok in q_counts:
            if tok not in tf:
                continue
            n_qi = df.get(tok, 0)
            idf = math.log((N - n_qi + 0.5) / (n_qi + 0.5) + 1)
            f = tf[tok]
            denom = f + k1 * (1 - b + b * dl / avg_dl)
            s += idf * (f * (k1 + 1)) / (denom or 1)
        if s > best_s:
            best_s, best_d = s, d
    return best_s, best_d