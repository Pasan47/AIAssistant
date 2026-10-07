"""Prompt-injection defence, input validation and output guardrails (pure functions, no I/O).

Defence in depth - no single layer is trusted:
  1. screen_user_message   : heuristic block of override / exfiltration / tool-abuse attempts.
  2. sanitize_untrusted    : neutralise instruction-like lines inside RETRIEVED documents
                             (indirect injection) before they reach any prompt.
  3. Prompts              : documents are wrapped as data and the model is told never to obey them.
  4. Registry + retriever : authorisation is enforced in code, so even a fooled LLM cannot
                             reach tools or documents the user's role does not allow.
  5. Output guardrails     : citation verification, secret/PAN redaction, brand-safety check.
Heuristics are a first filter, not a guarantee - see README "Security approach".
"""
import re
from dataclasses import dataclass

from app.config import settings

_FLAGS = re.IGNORECASE | re.DOTALL

_INJECTION_PATTERNS: dict[str, list[str]] = {
    "instruction_override": [
        r"\bignore (all |any |the )?(previous |prior |above |earlier |system )?(instructions|rules|prompts?)",
        r"\bdisregard (all |any |the )?(previous |prior |above |system )",
        r"\byou are now\b",
        r"\b(developer|dan|jailbreak|god) mode\b",
        r"\bpretend (to be|you are)\b",
        r"\bnew instructions\s*:",
    ],
    "data_exfiltration": [
        r"\b(reveal|show|print|repeat|display|leak|dump)\b.{0,40}\b(system prompt|hidden prompt|instructions|api[_ -]?keys?|secrets?|passwords?|credentials|tokens?)\b",
        r"\bsend\b.{0,40}\b(to|via)\b.{0,20}(https?://|e-?mail|webhook)",
        r"https?://\S+\?\S*=",
        r"\bbase64\b.{0,30}\b(encode|dump|documents?|data)\b",
    ],
    "tool_abuse": [
        r"\b(call|run|invoke|execute|use)\b.{0,25}\b(admin_reindex|admin tool|shell|subprocess|os\.system|eval|exec)\b",
        r"\bdrop table\b",
        r"\brm -rf\b",
        r"\b(bypass|skip|disable)\b.{0,25}\b(authori[sz]ation|permissions?|rbac|guardrails?|validation|filters?)\b",
    ],
}
_COMPILED = {k: [re.compile(p, _FLAGS) for p in v] for k, v in _INJECTION_PATTERNS.items()}

# Extra markers that only make sense inside *documents* (fake chat roles / special tokens).
_DOC_ONLY = [
    re.compile(r"^\s*(system|assistant|developer)\s*:", re.I),
    re.compile(r"<\|?\s*(system|im_start|im_end)\s*\|?>", re.I),
    re.compile(r"\[/?INST\]", re.I),
]
_ZERO_WIDTH = re.compile("[\u200b\u200c\u200d\u2060\ufeff]")
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")


@dataclass(frozen=True)
class Verdict:
    allowed: bool
    category: str = "ok"
    reason: str = ""


def screen_user_message(text: str) -> Verdict:
    """Validate and screen a user request before it reaches any LLM."""
    if not text or not text.strip():
        return Verdict(False, "invalid_request", "Message is empty.")
    if len(text) > settings.max_message_chars:
        return Verdict(False, "invalid_request", f"Message exceeds {settings.max_message_chars} characters.")
    if _CONTROL.search(text):
        return Verdict(False, "invalid_request", "Message contains control characters.")
    normalised = _ZERO_WIDTH.sub("", text)
    for category, patterns in _COMPILED.items():
        for pattern in patterns:
            if pattern.search(normalised):
                return Verdict(False, category, f"Matched {category} pattern.")
    return Verdict(True)


def sanitize_untrusted(text: str) -> tuple[str, bool]:
    """Neutralise instruction-like lines in retrieved content. Returns (clean_text, was_modified)."""
    text = _ZERO_WIDTH.sub("", text)
    flagged, out = False, []
    for line in text.splitlines():
        bad = any(p.search(line) for ps in _COMPILED.values() for p in ps) or any(p.search(line) for p in _DOC_ONLY)
        if bad:
            flagged = True
            out.append("[line removed: suspected instruction embedded in document]")
        else:
            out.append(line)
    return "\n".join(out), flagged


# ---------------------------------------------------------------- output guardrails
_CITATION = re.compile(r"\[([A-Za-z0-9_.\-]+#\d+)\]")
_SECRET_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9_\-]{20,}"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"(?i)\b(password|secret|api[_-]?key)\b\s*[:=]\s*\S+"),
]
_PAN = re.compile(r"\b(?:\d[ -]?){13,19}\b")
_BRAND_PATTERNS = [
    re.compile(r"(?i)\bguarantee[sd]?\b.{0,20}\b(returns?|profits?|approval)\b"),
    re.compile(r"(?i)\b(stupid|idiot|useless|shut up)\b"),
]


def _luhn_ok(digits: str) -> bool:
    total, alt = 0, False
    for ch in reversed(digits):
        d = int(ch)
        if alt:
            d = d * 2 - 9 if d * 2 > 9 else d * 2
        total, alt = total + d, not alt
    return total % 10 == 0


def redact_sensitive(text: str) -> tuple[str, int]:
    """Mask credentials and card numbers (Luhn-valid) in model output."""
    count = 0

    def _mask(_m: re.Match) -> str:
        nonlocal count
        count += 1
        return "[REDACTED]"

    for pat in _SECRET_PATTERNS:
        text = pat.sub(_mask, text)

    def _pan(m: re.Match) -> str:
        digits = re.sub(r"\D", "", m.group(0))
        return _mask(m) if 13 <= len(digits) <= 19 and _luhn_ok(digits) else m.group(0)

    return _PAN.sub(_pan, text), count


def check_citations(answer: str, allowed_ids: set[str]) -> tuple[str, list[str], list[str]]:
    """Strip hallucinated citations. Returns (clean_answer, invalid_ids, valid_ids)."""
    found = _CITATION.findall(answer)
    invalid = sorted({c for c in found if c not in allowed_ids})
    valid = sorted({c for c in found if c in allowed_ids})
    clean = _CITATION.sub(lambda m: m.group(0) if m.group(1) in allowed_ids else "", answer)
    return re.sub(r"[ \t]{2,}", " ", clean), invalid, valid


def brand_violations(answer: str) -> list[str]:
    return [p.pattern for p in _BRAND_PATTERNS if p.search(answer)]
