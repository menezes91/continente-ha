"""Cliente HTTP para o continente.pt.

Fala diretamente com os controllers do Salesforce Commerce Cloud, reutilizando
os cookies de uma sessão que iniciaste à mão no browser. Sem Selenium.
"""
from __future__ import annotations

import math
import re
from pathlib import Path

import requests

from . import parsing
from . import config
from .config import BASE, UA, url
from .session import (
    load_cookies,
    save_cookies,
    saved_was_authenticated as _saved_was_authenticated,
)


class ContinenteError(RuntimeError):
    """Falha ao falar com o continente.pt."""


class ContinenteClient:
    """Sessão reutilizável contra o continente.pt.

    >>> c = ContinenteClient()
    >>> c.search("banana", limit=3)
    >>> c.add_to_cart("2597619", quantity=1)
    >>> c.cart()
    """

    def __init__(self, session_file: Path | None = None, timeout: int = 30,
                 credentials: tuple[str, str] | None = None):
        self.timeout = timeout
        # As credenciais vêm da configuração da integração.
        self.credentials = credentials
        self._csrf: str | None = None
        self._csrf_absent = False
        self._quantity_rules: dict[str, dict] = {}
        self._url_cache: dict[str, str] = {}
        self._session_file: Path | None = None

        self.http = requests.Session()
        self.http.headers.update(
            {
                "User-Agent": UA,
                "Accept-Language": "pt-PT,pt;q=0.9,en;q=0.8",
            }
        )
        self.load_session(session_file or config.SESSION_FILE)

    # ------------------------------------------------------------------ sessão

    def load_session(self, session_file: Path | None = None) -> int:
        """Injeta os cookies guardados. Devolve quantos foram carregados."""
        session_file = session_file or config.SESSION_FILE
        self._session_file = session_file
        cookies = load_cookies(session_file)
        for c in cookies:
            self.http.cookies.set(
                c["name"], c["value"], domain=c.get("domain", ".continente.pt"),
                path=c.get("path", "/"),
            )
        return len(cookies)

    def looks_authenticated(self) -> bool:
        """Leitura barata do estado da sessão, sem ir à rede.

        O SFCC põe o número de cliente no `cquid`; anónimo vale `||`.
        """
        return bool((self.http.cookies.get("cquid") or "").strip("|"))

    def persist(self) -> Path | None:
        """Grava os cookies atuais, para o carrinho sobreviver ao processo.

        Nunca degrada uma sessão guardada: se a sessão em memória caiu para
        anónima (expirou a meio), gravá-la por cima da autenticada faria as
        operações seguintes irem parar a um carrinho de convidado.
        """
        if not self._session_file:
            return None
        if not self.looks_authenticated() and _saved_was_authenticated(self._session_file):
            return None
        cookies = [
            {"name": c.name, "value": c.value,
             "domain": c.domain or ".continente.pt", "path": c.path or "/"}
            for c in self.http.cookies
        ]
        return save_cookies(cookies, self._session_file,
                            authenticated=self.looks_authenticated())

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.persist()

    def is_authenticated(self) -> bool:
        """True se os cookies correspondem a uma conta com sessão iniciada.

        A área de conta redireciona para `/login/` quando a sessão é anónima.
        """
        r = self.http.get(url("Account-Show"), timeout=self.timeout,
                          allow_redirects=True)
        return "/login/" not in r.url

    def ensure_authenticated(self) -> bool:
        """Garante sessão iniciada, renovando-a se for preciso.

        A sessão do continente.pt expira depressa. Sem isto, qualquer tarefa
        que corra sozinha — o registo diário de preços, por exemplo — falharia
        assim que os cookies caducassem.
        """
        if self.is_authenticated():
            return True
        from .login import LoginError, login_http

        email, password = self.credentials or (None, None)
        try:
            login_http(email, password, session=self.http)
        except LoginError as exc:
            raise ContinenteError(
                f"sessão expirada e não consegui renovar: {exc}"
            ) from exc
        self._csrf, self._csrf_absent = None, False
        self.persist()
        return True

    def whoami(self) -> dict:
        cquid = self.http.cookies.get("cquid") or ""
        return {
            "authenticated": self.is_authenticated(),
            "customer_id": cquid.strip("|") or None,
            "cookies": len(self.http.cookies),
            "session_file": (str(config.SESSION_FILE)
                             if config.SESSION_FILE.exists() else None),
        }

    # -------------------------------------------------------------------- HTTP

    def _get(self, controller: str, **params) -> requests.Response:
        r = self.http.get(url(controller), params=params or None,
                          headers={"X-Requested-With": "XMLHttpRequest"},
                          timeout=self.timeout)
        r.raise_for_status()
        return r

    def _post(self, controller: str, data: dict) -> dict:
        token = self.csrf()
        r = self.http.post(
            url(controller),
            data={**data, "csrf_token": token} if token else data,
            headers={
                "X-Requested-With": "XMLHttpRequest",
                "Origin": BASE,
                "Referer": BASE + "/",
            },
            timeout=self.timeout,
        )
        r.raise_for_status()
        try:
            return r.json()
        except ValueError as exc:
            raise ContinenteError(f"{controller} não devolveu JSON") from exc

    def csrf(self, refresh: bool = False) -> str | None:
        """Token CSRF da sessão, ou `None` se o site não estiver a emitir um.

        Sessões anónimas recebem um token em cada página e o site exige-o.
        Sessões autenticadas não recebem nenhum — e também não o pedem.
        """
        if self._csrf and not refresh:
            return self._csrf
        if self._csrf_absent and not refresh:
            return None
        r = self.http.get(BASE + "/", timeout=self.timeout)
        self._csrf = parsing.csrf_token(r.text)
        self._csrf_absent = self._csrf is None
        return self._csrf

    # ---------------------------------------------------------------- pesquisa


    def search(self, query: str, limit: int = 24, start: int = 0) -> dict:
        """Pesquisa completa, com paginação."""
        results: list[dict] = []
        total: int | None = None
        page_size = 36  # o site pagina de 36 em 36

        while len(results) < limit:
            r = self._get("Search-ShowAjax", q=query,
                          start=start + len(results), sz=page_size)
            if total is None:
                total = parsing.total_count(r.text)
            page = parsing.parse_products(r.text)
            if not page:
                break
            known = {p["pid"] for p in results}
            fresh = [p for p in page if p["pid"] not in known]
            if not fresh:
                break
            results.extend(fresh)

        return {
            "query": query,
            "total": total if total is not None else len(results),
            "count": min(len(results), limit),
            "results": results[:limit],
        }

    # ---------------------------------------------------------------- produtos

    def product(self, pid_or_url: str) -> dict:
        """Detalhe de um produto, por `pid`, URL, ou slug."""
        product_url = self._resolve_url(pid_or_url)
        r = self.http.get(product_url, timeout=self.timeout)
        r.raise_for_status()
        if self._csrf is None:
            self._csrf = parsing.csrf_token(r.text)
        info = parsing.parse_product_page(r.text, r.url.split("?")[0])
        if info.get("pid"):
            self._quantity_rules[info["pid"]] = parsing.parse_quantity_rules(r.text)
        return info

    def _resolve_url(self, pid_or_url: str) -> str:
        """Aceita URL completo, slug, ou apenas o `pid`."""
        ref = str(pid_or_url).strip()
        if ref.startswith("http"):
            return ref.split("?")[0]
        if ref.startswith("/produto/"):
            return BASE + ref.split("?")[0]
        if not re.fullmatch(r"\d{5,}", ref):
            raise ContinenteError(f"referência de produto inválida: {pid_or_url!r}")
        if ref in self._url_cache:
            return self._url_cache[ref]
        # Só temos o pid: a pesquisa pelo próprio pid devolve o link canónico.
        r = self.http.get(f"{BASE}/pesquisa/", params={"q": ref}, timeout=self.timeout)
        m = re.search(rf'href="(/produto/[^"]*{ref}[^"]*)"', r.text)
        if not m:
            raise ContinenteError(f"produto {ref} não encontrado")
        self._url_cache[ref] = BASE + m.group(1).split("?")[0]
        return self._url_cache[ref]

    def quantity_rules(self, pid: str) -> dict:
        """Quantidade mínima e múltiplo aceites para um produto (em cache)."""
        if pid not in self._quantity_rules:
            self.product(pid)
        return self._quantity_rules.get(pid, {})

    @staticmethod
    def _snap_quantity(quantity: float, rules: dict) -> float:
        """Ajusta a quantidade ao mínimo e ao múltiplo exigidos pelo produto."""
        minimum = rules.get("min_quantity") or 0
        step = rules.get("step_quantity") or 0
        q = float(quantity)
        if step > 0:
            q = math.ceil(q / step) * step
        if minimum and q < minimum:
            q = minimum
        return round(q, 3)

    # ------------------------------------------------------------------ listas

    def my_list(self, list_name: str = "topSellersList") -> dict:
        """Uma das listas da tua conta (requer sessão autenticada).

        `topSellersList` são os produtos que compras mais vezes.
        """
        self.ensure_authenticated()
        r = self.http.get(
            f"{BASE}/conta/lista-produtos/", params={"list": list_name},
            timeout=self.timeout, allow_redirects=True,
        )
        r.raise_for_status()
        if "/login/" in r.url:
            raise ContinenteError(
                "esta lista precisa de sessão iniciada — corre `python cli.py login`"
            )
        return {"list": list_name, "products": parsing.parse_products(r.text)}

    # ---------------------------------------------------------------- carrinho

    def cart(self, require_auth: bool = True) -> dict:
        """Estado atual do carrinho.

        Uma sessão anónima também tem carrinho — mas é um carrinho de
        convidado, invisível na tua conta. Por omissão garantimos a sessão
        antes de lhe tocar, senão as compras iam parar a lado nenhum.
        """
        if require_auth:
            self.ensure_authenticated()
        r = self._get("Cart-MiniCartShow")
        data = r.json()
        cart = parsing.parse_basket(data.get("basket") or {})
        cart["authenticated"] = self.looks_authenticated()
        return cart

    def add_to_cart(
        self,
        pid_or_url: str,
        quantity: float = 1,
        adjust_quantity: bool = True,
    ) -> dict:
        """Adiciona um produto ao carrinho.

        `quantity` é na unidade de venda do produto (devolvida em `sent_unit`):
        kg num produto a peso, unidades nos restantes.

        O site aceita quantidades inválidas e depois não adiciona nada, sem
        assinalar erro. Por isso ajustamos a quantidade às regras do produto
        (`adjust_quantity`) e confirmamos o resultado no carrinho.
        """
        self.ensure_authenticated()
        # O carrinho só precisa do pid; a página do produto serve para ler as
        # regras de quantidade. Se ela não for alcançável — um produto que
        # saiu da pesquisa, por exemplo — adicionamos à mesma, sem ajuste.
        try:
            product_url = self._resolve_url(pid_or_url)
            pid = parsing.pid_from_url(product_url) or ""
        except ContinenteError:
            product_url, pid = None, str(pid_or_url).strip()

        if not re.fullmatch(r"\d{5,}", pid):
            raise ContinenteError(f"não consegui obter o pid de {pid_or_url!r}")

        if product_url:
            # Já temos o link canónico: evita que `quantity_rules` o volte a
            # procurar pelo pid (e falhe em produtos fora da pesquisa).
            self._url_cache.setdefault(pid, product_url)
            rules = self.quantity_rules(pid)
        else:
            rules = {}
        asked = float(quantity)
        qty = self._snap_quantity(asked, rules) if adjust_quantity else asked

        before = self._line_for(pid)
        payload = {
            "pid": pid,
            "quantity": _fmt_qty(qty),
            "options": "[]",
            "childProducts": "[]",
        }
        resp = self._post("Cart-AddProduct", payload)
        after = self._line_for(pid)

        added = after is not None and (
            before is None or (after.get("quantity") or 0) > (before.get("quantity") or 0)
        )
        result = {
            "ok": bool(added),
            "pid": pid,
            "url": product_url,
            "requested_quantity": asked,
            "sent_quantity": qty,
            "sent_unit": rules.get("primary_unit"),
            "quantity_adjusted": qty != asked,
            "message": resp.get("message"),
            "line": after,
            "quantity_rules": rules,
        }
        if not added:
            result["reason"] = _explain_failure(resp, asked, rules)
        return result

    def add_many(self, items: list[dict], adjust_quantity: bool = True) -> dict:
        """Adiciona vários produtos. `items`: [{"product": ..., "quantity": n}]."""
        self.ensure_authenticated()
        results = []
        for item in items:
            ref = item.get("product") or item.get("pid") or item.get("url")
            try:
                results.append(
                    self.add_to_cart(ref, item.get("quantity", 1), adjust_quantity)
                )
            except (ContinenteError, requests.RequestException) as exc:
                results.append({"ok": False, "pid": ref, "reason": str(exc)})
        return {
            "added": sum(1 for r in results if r.get("ok")),
            "failed": sum(1 for r in results if not r.get("ok")),
            "results": results,
            "cart": self.cart(),
        }


    def remove_from_cart(self, pid_or_url: str) -> dict:
        """Remove uma linha do carrinho."""
        self.ensure_authenticated()
        pid = parsing.pid_from_url(self._resolve_url(pid_or_url))
        line = self._line_for(pid)
        if not line:
            return {"ok": False, "pid": pid, "reason": "não está no carrinho"}
        self._get("Cart-RemoveProductLineItem", pid=pid, uuid=line["uuid"])
        return {"ok": self._line_for(pid) is None, "pid": pid}

    def empty_cart(self) -> dict:
        """Esvazia o carrinho, linha a linha.

        `Cart-RemoveAllProductLineItems` existe mas devolve 500; remover cada
        linha pelo seu uuid funciona sempre.
        """
        self.ensure_authenticated()
        for item in self.cart()["items"]:
            self._get("Cart-RemoveProductLineItem",
                      pid=item["pid"], uuid=item["uuid"])
        return self.cart()

    def _line_for(self, pid: str) -> dict | None:
        return next((i for i in self.cart()["items"] if i["pid"] == pid), None)


def _fmt_qty(q: float) -> str:
    """`6.0` -> `6`, `0.6` -> `0.6` (o site rejeita `6.0`)."""
    return str(int(q)) if float(q).is_integer() else str(q)


def _explain_failure(resp: dict, asked: float, rules: dict) -> str:
    message = resp.get("message") or ""
    if resp.get("isProductInStock") is False:
        return "produto sem stock"
    # O site devolve esta em inglês, e é a falha mais comum a seguir à
    # quantidade inválida.
    m = re.search(r'Only "([\d.]+)" items in stock', message)
    if m:
        available = float(m.group(1))
        return ("produto esgotado" if available == 0
                else f"só há {available:g} em stock (pediste {asked:g})")
    minimum, step = rules.get("min_quantity"), rules.get("step_quantity")
    if minimum and asked < minimum:
        return f"quantidade mínima é {minimum} {rules.get('primary_unit') or ''}".strip()
    if step and step > 1:
        return f"a quantidade tem de ser múltipla de {step}"
    return message or "o site não adicionou o produto e não explicou porquê"
