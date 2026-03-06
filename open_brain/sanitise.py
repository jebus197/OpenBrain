"""Input sanitisation for Open Brain.

Defence-in-depth: all writes come from trusted agents, but we still
strip obvious prompt-injection patterns and enforce size limits.
"""

import re

MAX_TEXT_BYTES = 50_000  # 50 KB

# Patterns that look like prompt injection / role reassignment
_INJECTION_PATTERNS = [
    re.compile(r"(?i)\bsystem\s*:\s"),
    re.compile(r"(?i)\b(ignore|disregard|forget)\s+(all\s+)?(previous|prior|above)\s+(instructions?|prompts?|context)"),
    re.compile(r"(?i)\byou\s+are\s+now\b"),
    re.compile(r"(?i)\bact\s+as\s+(a|an|if)\b"),
    re.compile(r"(?i)\bnew\s+instructions?\s*:"),
    re.compile(r"(?i)\b(override|bypass)\s+(safety|security|rules?|filters?|guardrails?)"),
    re.compile(r"(?i)\bdo\s+not\s+follow\s+(your|the)\s+(rules?|guidelines?|instructions?)"),
    re.compile(r"(?i)\bpretend\s+(you|to)\b"),
    re.compile(r"(?i)\brole\s*:\s*(system|admin|root)"),
]

_REDACTED = "[REDACTED]"


class SanitisationError(ValueError):
    """Raised when input fails sanitisation checks."""


def sanitise(text: str) -> str:
    """Sanitise text for storage.

    Raises SanitisationError for empty or oversized input.
    Returns cleaned text with injection patterns replaced.
    """
    if not text or not text.strip():
        raise SanitisationError("Empty text")

    if len(text.encode("utf-8")) > MAX_TEXT_BYTES:
        raise SanitisationError(
            f"Text exceeds {MAX_TEXT_BYTES} byte limit "
            f"({len(text.encode('utf-8'))} bytes)"
        )

    cleaned = text
    for pattern in _INJECTION_PATTERNS:
        cleaned = pattern.sub(_REDACTED, cleaned)

    return cleaned.strip()
