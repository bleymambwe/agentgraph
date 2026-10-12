"""Best-effort secret scrubbing so traces can be shared for audit.

This is a safety net, not a guarantee. Review a report before sending it outside
your team.
"""
from __future__ import annotations

import re

_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9_\-]{16,}"),
    re.compile(r"gh[pousr]_[A-Za-z0-9]{30,}"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"AIza[0-9A-Za-z_\-]{30,}"),
    re.compile(r"xox[baprs]-[A-Za-z0-9\-]{10,}"),
    re.compile(r"(?i)bearer\s+[A-Za-z0-9._\-]{20,}"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"(?i)\b(api[_-]?key|secret|token|password|passwd)\b(\s*[=:]\s*)(['\"]?)[^\s'\",;]{6,}"),
]


def redact(text: str) -> str:
    for pat in _PATTERNS[:-1]:
        text = pat.sub("[REDACTED]", text)
    return _PATTERNS[-1].sub(lambda m: m.group(1) + m.group(2) + m.group(3) + "[REDACTED]", text)
