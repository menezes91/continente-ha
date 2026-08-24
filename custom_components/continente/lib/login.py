"""Login automático com credenciais.

O continente.pt delega o login num SSO que vive num iframe
(`login.continente.pt`), em dois passos: primeiro o email, depois a password.

O fluxo é um OAuth2 PKCE normal contra a API REST do SSO, sem browser nenhum —
que é o que permite isto correr dentro do Home Assistant. A versão autónoma
tem ainda um caminho por Selenium, para quando o SSO pedir verificação extra;
aqui esse caminho não existe, porque não há Chrome num container.
"""
from __future__ import annotations

from pathlib import Path

from . import config
from .config import BASE
from .session import save_cookies

# O Selenium só é importado dentro das funções que abrem o browser: o caminho
# normal — `login_http` — não precisa dele, e assim corre onde não há Chrome
# nem o pacote instalado.

LOGIN_URL = f"{BASE}/login/"

# A API do SSO, por trás do iframe. Descoberta a ver os pedidos que a página
# faz durante um login verdadeiro (modo explorer, `net`).
SSO = "https://login.continente.pt"
SSO_CLIENT_ID = "NLR6WHyO8Iba4eRS"


class LoginError(RuntimeError):
    """O login automático não chegou ao fim."""



def login_http(email: str | None = None, password: str | None = None,
               session=None) -> dict:
    """Inicia sessão sem browser nenhum.

    O iframe do SSO é uma aplicação de página única sobre uma API REST, e o
    fluxo é um OAuth2 PKCE normal:

        POST /api/username                       o email
        POST /api/email/login/validate-password  a password
        GET  /api/credentials/authorize          devolve o código
        POST Account-Login                       troca o código pela sessão

    Quatro pedidos, contra abrir o Chrome. Se o SSO exigir uma verificação
    extra, isto falha e o caminho pelo browser (`login`) continua a servir.

    `session` permite reaproveitar um `requests.Session` já existente — é como
    o cliente renova a sessão sem perder o resto do estado.
    """
    import base64
    import hashlib
    import secrets

    import requests

    from .config import UA, url as ctrl

    if not email or not password:
        raise LoginError("faltam as credenciais do Continente")

    http = session or requests.Session()
    http.headers.setdefault("User-Agent", UA)
    http.headers.setdefault("Accept-Language", "pt-PT,pt;q=0.9")
    json_headers = {
        "Content-Type": "application/json",
        "Referer": f"{SSO}/user-register?clientId={SSO_CLIENT_ID}",
        "Origin": SSO,
    }

    def step(name, response):
        if response.status_code >= 400:
            raise LoginError(f"{name} devolveu {response.status_code}: "
                             f"{response.text[:200]}")
        return response

    try:
        http.get(BASE + "/", timeout=30)
        step("o passo do email", http.post(
            f"{SSO}/api/username",
            json={"username": email, "clientId": SSO_CLIENT_ID, "returnUrl": None},
            headers=json_headers, timeout=30))
        step("o passo da password", http.post(
            f"{SSO}/api/email/login/validate-password",
            json={"passwordRecover": False, "password": password},
            headers=json_headers, timeout=30))

        verifier = secrets.token_hex(28)
        challenge = base64.urlsafe_b64encode(
            hashlib.sha256(verifier.encode()).digest()
        ).decode().rstrip("=")
        authorize = step("o pedido do código", http.get(
            f"{SSO}/api/credentials/authorize",
            params={"clientId": SSO_CLIENT_ID, "codeChallenge": challenge,
                    "codeChallengeMethod": "S256"},
            headers=json_headers, timeout=30))
        code = authorize.json().get("authorizationCode")
        if not code:
            raise LoginError("o SSO não devolveu código de autorização — "
                             "pode estar a pedir verificação extra")

        result = step("a troca pelo cookie de sessão", http.post(
            ctrl("Account-Login"),
            data={"authorizationCode": code, "codeVerifier": verifier,
                  "ssoLogin": "false", "rurl": "null"},
            headers={
                "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
                "Referer": LOGIN_URL, "Origin": BASE,
                "X-Requested-With": "XMLHttpRequest",
            }, timeout=30))
        if not result.json().get("success"):
            raise LoginError(f"o site recusou o código: {result.text[:200]}")
    except requests.RequestException as exc:
        raise LoginError(f"login sem browser falhou: {exc}") from exc

    # O número de cliente só aparece nos cookies depois de navegar uma vez.
    http.get(BASE + "/", timeout=30)

    cookies = [
        {"name": c.name, "value": c.value,
         "domain": c.domain or ".continente.pt", "path": c.path or "/"}
        for c in http.cookies
    ]
    if not any(c["name"] == "cquid" and c["value"].strip("|") for c in cookies):
        raise LoginError("a sessão ficou anónima depois do login")
    path = save_cookies(cookies, config.SESSION_FILE, authenticated=True)
    return {"ok": True, "steps": ["login sem browser"], "session_file": str(path)}
