"""Fake secrets, assembled at runtime.

No literal secret-shaped string may appear in this repo (AGENTS.md invariant 13), so every
sample here is built from fragments.
"""

from __future__ import annotations

_B64 = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/"


def aws_key_id() -> str:
    return "AK" + "IA" + "Q" * 16


def aws_secret_line() -> str:
    return "aws_secret_access_key = " + (_B64 * 2)[:40]


def github_token() -> str:
    return "gh" + "p_" + "A" * 36


def github_pat() -> str:
    return "github" + "_pat_" + "B" * 30


def slack_token() -> str:
    return "xo" + "xb-" + "1234567890-abcdefghij"


def private_key_block() -> str:
    head = "-----BEGIN " + "RSA PRIVATE KEY" + "-----"
    tail = "-----END " + "RSA PRIVATE KEY" + "-----"
    return head + "\n" + ("MIIE" + "x" * 60 + "\n") * 3 + tail


def bearer_line() -> str:
    return "Authorization: Bearer " + "z" * 48


def jwt() -> str:
    return "ey" + "J0eXAiOiJKV1QifQ" + "." + "eyJzdWIiOiIxIn0" + "." + "c2lnbmF0dXJl"


def kv_secret_line() -> str:
    return "password=" + "hunter2hunter2"


def all_samples() -> dict[str, str]:
    return {
        "aws_key_id": aws_key_id(),
        "aws_secret": aws_secret_line(),
        "github_token": github_token(),
        "github_pat": github_pat(),
        "slack_token": slack_token(),
        "private_key": private_key_block(),
        "bearer": bearer_line(),
        "jwt": jwt(),
        "kv_secret": kv_secret_line(),
    }


def near_misses() -> list[str]:
    """Strings that look secret-ish but must survive untouched."""
    return [
        "AK" + "IA" + "short",
        "gh" + "p_" + "tooshort",
        "a normal sentence about a password policy",
        "token_count=1024",
        "Authorization: Basic dXNlcjpwYXNz",
    ]
