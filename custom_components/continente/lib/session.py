"""Captura e reutilização da sessão autenticada.

O login do continente.pt não é automatizado de propósito: é feito à mão numa
janela de Chrome com perfil persistente. Daí extraímos os cookies de sessão
para `sessao.json`, que o cliente HTTP reutiliza sem voltar a abrir o browser.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from . import config
from .config import SESSION_COOKIE_PREFIXES


def _is_session_cookie(name: str) -> bool:
    return any(name.startswith(p) for p in SESSION_COOKIE_PREFIXES)


def cookies_are_authenticated(cookies: list[dict]) -> bool:
    """True se estes cookies trazem um número de cliente (`cquid` != `||`)."""
    for c in cookies:
        if c.get("name") == "cquid":
            return bool((c.get("value") or "").strip("|"))
    return False


def saved_was_authenticated(path: Path | None = None) -> bool:
    """Se a sessão em disco pertence a uma conta com sessão iniciada."""
    path = path or config.SESSION_FILE
    if not path.exists():
        return False
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return False
    if "authenticated" in data:
        return bool(data["authenticated"])
    return cookies_are_authenticated(data.get("cookies", []))


def save_cookies(cookies: list[dict], path: Path | None = None,
                 authenticated: bool | None = None) -> Path:
    """Guarda os cookies relevantes em disco."""
    path = path or config.SESSION_FILE
    keep = [c for c in cookies if _is_session_cookie(c["name"])]
    payload = {
        "saved_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "authenticated": (cookies_are_authenticated(keep)
                          if authenticated is None else authenticated),
        "cookies": [
            {
                "name": c["name"],
                "value": c["value"],
                "domain": c.get("domain", ".continente.pt"),
                "path": c.get("path", "/"),
            }
            for c in keep
        ],
    }
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def load_cookies(path: Path | None = None) -> list[dict]:
    """Lê os cookies guardados. Lista vazia se ainda não houver sessão."""
    path = path or config.SESSION_FILE
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8")).get("cookies", [])


