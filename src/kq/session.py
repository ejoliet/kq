"""Session id resolution, paths, and environment configuration."""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class SessionPaths:
    id: str
    dir: Path

    @property
    def db(self) -> Path:
        # AIDEV-NOTE: not kq.duckdb — DuckDB names the catalog after the file, and a catalog
        # named `kq` makes every `kq.events` reference ambiguous with the metadata schema.
        return self.dir / "session.duckdb"

    @property
    def artifacts(self) -> Path:
        return self.dir / "artifacts"

    @property
    def pinned(self) -> Path:
        return self.dir / "pinned"


def root() -> Path:
    home = os.environ.get("KQ_HOME")
    if home:
        return Path(home)
    xdg = os.environ.get("XDG_DATA_HOME")
    if xdg:
        return Path(xdg) / "kq"
    return Path.home() / ".local" / "share" / "kq"


def session_id_for_dir(cwd: Path | None = None) -> str:
    p = Path(cwd or Path.cwd()).resolve()
    digest = hashlib.sha256(str(p).encode()).hexdigest()[:8]
    return f"{p.name}-{digest}"


def resolve_session(explicit: str | None = None, *, create: bool = True) -> SessionPaths:
    sid = explicit or os.environ.get("KQ_SESSION")
    if not sid:
        default = session_id_for_dir()
        pinned = root() / "sessions" / default / "pinned"
        sid = pinned.read_text().strip() if pinned.exists() else default
    d = root() / "sessions" / sid
    if create:
        (d / "artifacts").mkdir(parents=True, exist_ok=True)
    return SessionPaths(sid, d)


def _env_num(name: str, default, cast):
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    try:
        return cast(raw)
    except ValueError:
        return default


def threshold_tokens() -> int:
    return _env_num("KQ_THRESHOLD_TOKENS", 2000, int)


def max_bytes() -> int:
    return _env_num("KQ_MAX_BYTES", 2147483648, int)


def lock_timeout() -> float:
    return _env_num("KQ_LOCK_TIMEOUT_S", 5.0, float)
