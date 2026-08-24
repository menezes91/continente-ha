"""As rotas HTTP que o painel usa.

São a tradução direta da API FastAPI da versão autónoma. Cada uma corre o
trabalho no executor, porque a biblioteca por baixo é síncrona.

Sobre autenticação: o painel é um iframe e não carrega o token do Home
Assistant, por isso estas rotas correm com `requires_auth = False`. Ficam
acessíveis a quem já alcança o Home Assistant na rede — não as exponhas à
internet sem uma camada à frente.
"""
from __future__ import annotations

import logging
from pathlib import Path

from aiohttp import web
from homeassistant.components.http import HomeAssistantView
from homeassistant.core import HomeAssistant

from .const import API_BASE, DOMAIN
from .lib.client import ContinenteError
from .lib.cookidoo import CookidooError

_LOGGER = logging.getLogger(__name__)
PANEL_DIR = Path(__file__).parent / "panel"


def _coordinator(hass: HomeAssistant):
    data = hass.data.get(DOMAIN) or {}
    if not data:
        raise web.HTTPServiceUnavailable(reason="integração não configurada")
    return next(iter(data.values()))


async def _run(hass: HomeAssistant, fn, *args):
    """Corre no executor e traduz os erros da biblioteca para HTTP."""
    try:
        return web.json_response(
            await hass.async_add_executor_job(fn, *args)
        )
    except (ContinenteError, CookidooError) as exc:
        return web.json_response({"detail": str(exc)}, status=400)
    except Exception as exc:  # noqa: BLE001 - a UI mostra a mensagem
        _LOGGER.exception("erro a servir o painel")
        return web.json_response({"detail": str(exc)}, status=500)


class PanelPageView(HomeAssistantView):
    """Serve a app de mapeamento e a de preços."""

    url = f"{API_BASE}/panel/{{page}}"
    name = "api:continente:panel"
    requires_auth = False

    async def get(self, request: web.Request, page: str) -> web.Response:
        if page not in ("app.html", "precos.html"):
            raise web.HTTPNotFound
        path = PANEL_DIR / page
        return web.Response(
            body=await request.app["hass"].async_add_executor_job(path.read_bytes),
            content_type="text/html",
            charset="utf-8",
        )


class ListView(HomeAssistantView):
    url = f"{API_BASE}/sync/list"
    name = "api:continente:list"
    requires_auth = False

    async def get(self, request: web.Request) -> web.Response:
        hass = request.app["hass"]
        c = _coordinator(hass)
        refresh = request.query.get("refresh") == "true"
        return await _run(hass, lambda: c.sync.shopping_list(refresh=refresh))


class CandidatesView(HomeAssistantView):
    url = f"{API_BASE}/sync/candidates"
    name = "api:continente:candidates"
    requires_auth = False

    async def post(self, request: web.Request) -> web.Response:
        hass = request.app["hass"]
        c = _coordinator(hass)
        body = await request.json()
        terms = body.get("terms") or []
        return await _run(hass, lambda: c.sync.candidates_for(terms))


class SearchView(HomeAssistantView):
    url = f"{API_BASE}/sync/search"
    name = "api:continente:search"
    requires_auth = False

    async def get(self, request: web.Request) -> web.Response:
        hass = request.app["hass"]
        c = _coordinator(hass)
        q = request.query.get("q", "")
        return await _run(hass, lambda: {"results": c.sync.search(q)})


class MapView(HomeAssistantView):
    url = f"{API_BASE}/sync/map"
    name = "api:continente:map"
    requires_auth = False

    async def post(self, request: web.Request) -> web.Response:
        hass = request.app["hass"]
        c = _coordinator(hass)
        b = await request.json()
        return await _run(hass, lambda: c.sync.map_item(
            b["term"], b["pid"], b.get("name", ""),
            b.get("quantity", 1), b.get("replace", True)))

    async def delete(self, request: web.Request) -> web.Response:
        hass = request.app["hass"]
        c = _coordinator(hass)
        term = request.query["term"]
        return await _run(hass, lambda: {"forgotten": c.sync.unmap_item(term)})


class MapOptionView(HomeAssistantView):
    url = f"{API_BASE}/sync/map/option"
    name = "api:continente:map:option"
    requires_auth = False

    async def delete(self, request: web.Request) -> web.Response:
        hass = request.app["hass"]
        c = _coordinator(hass)
        term, pid = request.query["term"], request.query["pid"]
        return await _run(hass, lambda: {"removed": c.sync.unmap_option(term, pid)})


class BestView(HomeAssistantView):
    url = f"{API_BASE}/sync/best"
    name = "api:continente:best"
    requires_auth = False

    async def get(self, request: web.Request) -> web.Response:
        hass = request.app["hass"]
        c = _coordinator(hass)
        return await _run(hass, lambda: c.sync.pick_best(request.query["term"]))


class QuantityView(HomeAssistantView):
    url = f"{API_BASE}/sync/quantity"
    name = "api:continente:quantity"
    requires_auth = False

    async def patch(self, request: web.Request) -> web.Response:
        hass = request.app["hass"]
        c = _coordinator(hass)
        term = request.query["term"]
        qty = float(request.query["quantity"])
        return await _run(hass, lambda: {"options": c.sync.set_quantity(term, qty)})


class IgnoreView(HomeAssistantView):
    url = f"{API_BASE}/sync/ignore"
    name = "api:continente:ignore"
    requires_auth = False

    async def post(self, request: web.Request) -> web.Response:
        hass = request.app["hass"]
        c = _coordinator(hass)
        b = await request.json()
        return await _run(hass, lambda: c.sync.ignore_item(b["term"]))


class SendView(HomeAssistantView):
    url = f"{API_BASE}/sync/send"
    name = "api:continente:send"
    requires_auth = False

    async def post(self, request: web.Request) -> web.Response:
        hass = request.app["hass"]
        c = _coordinator(hass)
        b = await request.json()
        try:
            result = await c.async_send_list(mark_done=b.get("mark_done", True))
        except (ContinenteError, CookidooError) as exc:
            return web.json_response({"detail": str(exc)}, status=400)
        return web.json_response(result)


class CartView(HomeAssistantView):
    url = f"{API_BASE}/cart"
    name = "api:continente:cart"
    requires_auth = False

    async def get(self, request: web.Request) -> web.Response:
        hass = request.app["hass"]
        c = _coordinator(hass)
        return await _run(hass, c.client.cart)

    async def delete(self, request: web.Request) -> web.Response:
        hass = request.app["hass"]
        c = _coordinator(hass)
        return web.json_response(await c.async_empty_cart())


class ProductView(HomeAssistantView):
    url = f"{API_BASE}/product/{{ref:.*}}"
    name = "api:continente:product"
    requires_auth = False

    async def get(self, request: web.Request, ref: str) -> web.Response:
        hass = request.app["hass"]
        c = _coordinator(hass)
        return await _run(hass, lambda: c.client.product(ref))


class PricesTrackedView(HomeAssistantView):
    url = f"{API_BASE}/prices/tracked"
    name = "api:continente:prices:tracked"
    requires_auth = False

    async def get(self, request: web.Request) -> web.Response:
        hass = request.app["hass"]
        c = _coordinator(hass)
        return await _run(hass, lambda: {
            "products": c.history.tracked(), "stats": c.history.stats()})


class PricesSnapshotView(HomeAssistantView):
    url = f"{API_BASE}/prices/snapshot"
    name = "api:continente:prices:snapshot"
    requires_auth = False

    async def post(self, request: web.Request) -> web.Response:
        c = _coordinator(request.app["hass"])
        return web.json_response(await c.async_snapshot_prices())


class PriceHistoryView(HomeAssistantView):
    url = f"{API_BASE}/prices/{{pid}}"
    name = "api:continente:prices:one"
    requires_auth = False

    async def get(self, request: web.Request, pid: str) -> web.Response:
        hass = request.app["hass"]
        c = _coordinator(hass)
        return await _run(hass, lambda: c.history.history(pid))


ALL_VIEWS = [
    PanelPageView, ListView, CandidatesView, SearchView, MapView,
    MapOptionView, BestView, QuantityView, IgnoreView, SendView,
    CartView, ProductView, PricesTrackedView, PricesSnapshotView,
    PriceHistoryView,
]


def register_views(hass: HomeAssistant) -> None:
    for view in ALL_VIEWS:
        hass.http.register_view(view())
