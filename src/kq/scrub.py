"""Secret patterns and redaction. Applied to bytes before anything reaches disk."""

from __future__ import annotations

import re

# AIDEV-NOTE: patterns are bytes so non-UTF-8 output can be scrubbed without a lossy decode.
# Order matters: specific token shapes run before the generic key=value rule.
PATTERNS: list[tuple[str, re.Pattern[bytes], int]] = [
    ("aws_key_id", re.compile(rb"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"), 0),
    (
        "aws_secret",
        re.compile(
            rb"(?i)(aws_secret_access_key|SecretAccessKey)(\"?\s*[=:]\s*\"?)([A-Za-z0-9/+=]{40})"
        ),
        3,
    ),
    ("github_token", re.compile(rb"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{36}\b"), 0),
    ("github_token", re.compile(rb"\bgithub_pat_[A-Za-z0-9_]{22,}\b"), 0),
    ("slack_token", re.compile(rb"\bxox[abprs]-[A-Za-z0-9-]{10,}"), 0),
    (
        "private_key",
        re.compile(rb"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----"),
        0,
    ),
    ("bearer", re.compile(rb"(?i)(\bauthorization:\s*bearer\s+)(\S+)"), 2),
    ("jwt", re.compile(rb"\beyJ[A-Za-z0-9_-]{4,}\.[A-Za-z0-9_-]{4,}\.[A-Za-z0-9_-]{4,}"), 0),
    (
        "kv_secret",
        re.compile(
            rb"(?i)\b(password|passwd|secret|token|api[_-]?key)(\"?\s*[=:]\s*\"?)"
            rb"(?!\[REDACTED)([^\s\"',]+)"
        ),
        3,
    ),
]


def scrub_bytes(data: bytes) -> tuple[bytes, int]:
    total = 0
    for kind, pattern, group in PATTERNS:
        replacement = f"[REDACTED:{kind}]".encode()

        def repl(m: re.Match[bytes], g: int = group, r: bytes = replacement) -> bytes:
            if g == 0:
                return r
            return m.group(0)[: m.start(g) - m.start(0)] + r

        data, n = pattern.subn(repl, data)
        total += n
    return data, total


def scrub_text(text: str) -> tuple[str, int]:
    out, n = scrub_bytes(text.encode("utf-8", "surrogateescape"))
    return out.decode("utf-8", "replace"), n
