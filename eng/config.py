"""Load config.yaml and .env."""

from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent


def load(path: str | Path = "config.yaml") -> dict:
    p = Path(path)
    if not p.is_absolute():
        p = ROOT / p
    with p.open(encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def load_env() -> None:
    """Read .env if python-dotenv is installed. Silent no-op otherwise."""
    try:
        from dotenv import load_dotenv
        load_dotenv(ROOT / ".env")
    except ImportError:
        pass
