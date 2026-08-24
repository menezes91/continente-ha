"""Leitura periódica do Continente e do Cookidoo.

A biblioteca é síncrona (`requests`), por isso todas as idas ao site correm no
executor — nunca no event loop do Home Assistant.
"""
from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    CONF_CONTINENTE_EMAIL,
    CONF_COOKIDOO_EMAIL,
    CONF_COOKIDOO_PASSWORD,
    CONF_CONTINENTE_PASSWORD,
    CONF_SCAN_MINUTES,
    DEFAULT_SCAN_MINUTES,
    DOMAIN,
)
from .lib.client import ContinenteClient, ContinenteError
from .lib.cookidoo import CookidooError
from .lib.prices import PriceHistory, snapshot
from .lib.sync import ShoppingSync

_LOGGER = logging.getLogger(__name__)


class ContinenteCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Mantém o estado do carrinho, da lista e dos preços."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        minutes = entry.options.get(CONF_SCAN_MINUTES, DEFAULT_SCAN_MINUTES)
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(minutes=minutes),
        )
        self.entry = entry
        self.client = ContinenteClient(
            credentials=(
                entry.data[CONF_CONTINENTE_EMAIL],
                entry.data[CONF_CONTINENTE_PASSWORD],
            )
        )
        self.sync = ShoppingSync(
            self.client,
            cookidoo_credentials=(
                entry.data.get(CONF_COOKIDOO_EMAIL) or "",
                entry.data.get(CONF_COOKIDOO_PASSWORD) or "",
            ),
        )
        self.history = PriceHistory()

    async def _async_update_data(self) -> dict[str, Any]:
        return await self.hass.async_add_executor_job(self._read)

    def _read(self) -> dict[str, Any]:
        """Corre no executor: pode bloquear à vontade."""
        try:
            cart = self.client.cart()
        except ContinenteError as exc:
            raise UpdateFailed(f"carrinho: {exc}") from exc

        listing: dict[str, Any] = {"items": [], "counts": {}, "erro": None}
        try:
            listing = self.sync.shopping_list(refresh=True)
        except CookidooError as exc:
            # Sem Cookidoo ainda há carrinho e preços; não vale a pena falhar
            # a atualização inteira por causa disso.
            listing["erro"] = str(exc)
            _LOGGER.warning("lista do Cookidoo indisponível: %s", exc)

        return {
            "cart": cart,
            "list": listing,
            "tracked": self.history.tracked(),
            "prices": self.history.stats(),
        }

    # ------------------------------------------------------------- ações

    async def async_send_list(self, mark_done: bool = True) -> dict:
        result = await self.hass.async_add_executor_job(
            lambda: self.sync.send_to_cart(mark_done=mark_done)
        )
        await self.async_request_refresh()
        return result

    async def async_add_product(self, product: str, quantity: float = 1) -> dict:
        result = await self.hass.async_add_executor_job(
            lambda: self.client.add_to_cart(product, quantity)
        )
        await self.async_request_refresh()
        return result

    async def async_remove_product(self, product: str) -> dict:
        result = await self.hass.async_add_executor_job(
            lambda: self.client.remove_from_cart(product)
        )
        await self.async_request_refresh()
        return result

    async def async_empty_cart(self) -> dict:
        result = await self.hass.async_add_executor_job(self.client.empty_cart)
        await self.async_request_refresh()
        return result

    async def async_snapshot_prices(self) -> dict:
        def work() -> dict:
            extra = [
                e["pid"]
                for entries in self.sync.store.rows.values()
                for e in entries
                if e["pid"].isdigit()
            ]
            return snapshot(self.client, extra, self.history)

        result = await self.hass.async_add_executor_job(work)
        await self.async_request_refresh()
        return result
