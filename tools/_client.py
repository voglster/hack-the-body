"""Shared HTTP client for the tools/ scripts.

Loads HTB_API_URL + HTB_API_KEY from tools/.env (per-tool config, kept out
of git). Every script uses `client()` so swapping hosts is one env var.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import httpx
from dotenv import load_dotenv

_ROOT = Path(__file__).resolve().parent
load_dotenv(_ROOT / ".env")


def _required(name: str) -> str:
    val = os.environ.get(name)
    if not val or val == "replace-me":
        sys.stderr.write(
            f"error: {name} not set — copy tools/.env.example to tools/.env and fill it in\n"
        )
        sys.exit(2)
    return val


def client() -> httpx.Client:
    base = _required("HTB_API_URL").rstrip("/")
    key = _required("HTB_API_KEY")
    return httpx.Client(
        base_url=base,
        headers={"X-API-Key": key},
        timeout=30.0,
    )
