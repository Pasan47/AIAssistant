"""Token-aware chunking (assumption: 500-800 token chunks, configurable)."""
import re

try:
    import tiktoken

    _ENC = tiktoken.get_encoding("cl100k_base")
except Exception:  # offline / missing BPE file: fall back to a word-based estimate
    _ENC = None


def count_tokens(text: str) -> int:
    return len(_ENC.encode(text)) if _ENC else int(len(text.split()) * 1.3) + 1


def _split_long(paragraph: str, max_tokens: int) -> list[str]:
    """A single paragraph larger than the limit is split on sentence boundaries."""
    parts, cur, cur_t = [], [], 0
    for sentence in re.split(r"(?<=[.!?])\s+", paragraph):
        t = count_tokens(sentence)
        if cur and cur_t + t > max_tokens:
            parts.append(" ".join(cur))
            cur, cur_t = [], 0
        cur.append(sentence)
        cur_t += t
    if cur:
        parts.append(" ".join(cur))
    return parts


def _overlap_tail(units: list[str], overlap_tokens: int) -> tuple[list[str], int]:
    """Carry the last small unit(s) into the next chunk for context continuity."""
    tail, total = [], 0
    for u in reversed(units):
        t = count_tokens(u)
        if t > overlap_tokens * 2 or total + t > overlap_tokens * 2:
            break
        tail.insert(0, u)
        total += t
        if total >= overlap_tokens:
            break
    return tail, total


def chunk_text(text: str, min_tokens: int = 500, max_tokens: int = 800, overlap_tokens: int = 80) -> list[str]:
    """Greedy paragraph packing up to max_tokens; also break at markdown headings once min_tokens is reached."""
    units: list[str] = []
    for p in (p.strip() for p in re.split(r"\n\s*\n", text)):
        if not p:
            continue
        units.extend([p] if count_tokens(p) <= max_tokens else _split_long(p, max_tokens))

    chunks: list[str] = []
    cur: list[str] = []
    cur_t = 0
    has_new = False
    for u in units:
        t = count_tokens(u)
        heading_break = u.startswith("#") and cur_t >= min_tokens
        if cur and has_new and (cur_t + t > max_tokens or heading_break):
            chunks.append("\n\n".join(cur))
            cur, cur_t = _overlap_tail(cur, overlap_tokens)
            has_new = False
        cur.append(u)
        cur_t += t
        has_new = True
    if cur and has_new:
        chunks.append("\n\n".join(cur))
    return chunks
