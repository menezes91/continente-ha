"""Leitura da lista de compras do Cookidoo.

Assenta na `cookidoo-api` (a mesma biblioteca que a integração do Cookidoo no
Home Assistant usa), que trata do OAuth2 do Vorwerk. Aqui só se envolve o
`asyncio` numa interface síncrona e se guardam os cookies, para não repetir o
login a cada chamada.
"""
from __future__ import annotations

import asyncio
from pathlib import Path

import aiohttp
from cookidoo_api import (
    Cookidoo,
    CookidooAuthException,
    CookidooConfig,
    CookidooLocalizationConfig,
)

from . import config

PT = CookidooLocalizationConfig(
    country_code="pt", language="pt-PT", url="https://cookidoo.pt/foundation/pt-PT"
)


class CookidooError(RuntimeError):
    """Falha a falar com o Cookidoo."""


def _key(name: str) -> str:
    """Nome comparável entre ingredientes de receita e itens da lista."""
    import unicodedata

    text = unicodedata.normalize("NFKD", (name or "").strip().lower())
    return "".join(c for c in text if not unicodedata.combining(c))


def _require(email: str | None, password: str | None) -> tuple[str, str]:
    """As credenciais vêm da configuração da integração, e mais nada."""
    if not email or not password:
        raise CookidooError(
            "faltam as credenciais do Cookidoo — mete-as na configuração da "
            "integração (Definições → Dispositivos e Serviços → Continente)"
        )
    return email, password


class CookidooClient:
    """Interface síncrona sobre a `cookidoo-api`."""

    def __init__(self, email: str | None = None, password: str | None = None,
                 cookie_file: Path | None = None):
        email, password = _require(email, password)
        self.email = email
        self.password = password
        self.cookie_file = cookie_file or config.COOKIDOO_COOKIES

    # ------------------------------------------------------------------ dados

    def shopping_list(self) -> dict:
        """A lista de compras inteira: ingredientes, extras e receitas."""
        return self._run(self._shopping_list())

    def clear(self) -> None:
        """Esvazia a lista de compras no Cookidoo."""
        self._run(self._call(lambda c: c.clear_shopping_list()))

    def mark_owned(self, ingredient_ids: list[str],
                   additional_ids: list[str]) -> None:
        """Passa itens para "Itens que tem" no Cookidoo.

        O campo chama-se `isOwned`, o que sugere autoria — não é. Verificado
        contra a interface: a lista tem duas secções, e os itens com
        `isOwned: true` são exatamente os que estão em **"Itens que tem"**,
        com o visto verde. Os de cima, por comprar, têm `isOwned: false`.
        """
        self._run(self._mark_owned(ingredient_ids, additional_ids))

    # -------------------------------------------------------------- interno

    async def _shopping_list(self) -> dict:
        async def work(c: Cookidoo) -> dict:
            ingredients = await c.get_ingredient_items()
            additional = await c.get_additional_items()
            recipes = await c.get_shopping_list_recipes()

            # De que receitas vem cada ingrediente. Os ids não são os mesmos
            # dos dois lados — o cruzamento tem de ser pelo nome.
            by_name: dict[str, list[str]] = {}
            for r in recipes:
                for ing in r.ingredients:
                    by_name.setdefault(_key(ing.name), []).append(r.name)

            return {
                "ingredients": [
                    {
                        "id": i.id,
                        "name": i.name,
                        "amount": getattr(i, "description", "") or "",
                        "owned": i.is_owned,
                        "source": "receita",
                        "recipes": by_name.get(_key(i.name), []),
                    }
                    for i in ingredients
                ],
                "additional": [
                    {
                        "id": a.id,
                        "name": a.name,
                        "amount": "",
                        "owned": a.is_owned,
                        "source": "extra",
                        "recipes": [],
                    }
                    for a in additional
                ],
                "recipes": [{"id": r.id, "name": r.name, "url": r.url}
                            for r in recipes],
            }

        return await self._call(work)

    async def _mark_owned(self, ingredient_ids: list[str],
                          additional_ids: list[str]) -> None:
        async def work(c: Cookidoo) -> None:
            if ingredient_ids:
                items = [i for i in await c.get_ingredient_items()
                         if i.id in ingredient_ids]
                for i in items:
                    i.is_owned = True
                await c.edit_ingredient_items_ownership(items)
            if additional_ids:
                items = [a for a in await c.get_additional_items()
                         if a.id in additional_ids]
                for a in items:
                    a.is_owned = True
                await c.edit_additional_items_ownership(items)

        await self._call(work)

    async def _call(self, work):
        """Corre `work` com sessão autenticada, reaproveitando cookies.

        Tenta primeiro com os cookies guardados; só faz login se não servirem.
        """
        jar = aiohttp.CookieJar(unsafe=True)
        reused = False
        if self.cookie_file.exists():
            try:
                jar.load(self.cookie_file)
                reused = True
            except (OSError, EOFError, ValueError):
                reused = False

        async with aiohttp.ClientSession(cookie_jar=jar) as session:
            client = Cookidoo(
                session,
                cfg=CookidooConfig(localization=PT, email=self.email,
                                   password=self.password),
            )
            if reused:
                try:
                    return await work(client)
                except Exception:  # cookies velhos: cai para o login
                    reused = False
            try:
                await client.login()
            except CookidooAuthException as exc:
                raise CookidooError(
                    f"o Cookidoo recusou as credenciais: {exc}"
                ) from exc
            except Exception as exc:
                raise CookidooError(f"login no Cookidoo falhou: {exc}") from exc
            try:
                jar.save(self.cookie_file)
            except OSError:
                pass
            return await work(client)

    @staticmethod
    def _run(coro):
        try:
            return asyncio.run(coro)
        except CookidooError:
            raise
        except Exception as exc:
            raise CookidooError(str(exc)) from exc
