"""Integração Continente: lista do Cookidoo, carrinho e preços."""
from __future__ import annotations

import logging

import voluptuous as vol
from homeassistant.components import frontend, panel_custom
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import config_validation as cv

from .const import (
    API_BASE,
    DOMAIN,
    PANEL_ICON,
    PANEL_TITLE,
    PANEL_URL_PATH,
    SERVICE_ADD_PRODUCT,
    SERVICE_EMPTY_CART,
    SERVICE_REMOVE_PRODUCT,
    SERVICE_SEND_LIST,
    SERVICE_SNAPSHOT_PRICES,
)
from .coordinator import ContinenteCoordinator
from .views import register_views

_LOGGER = logging.getLogger(__name__)
PLATFORMS = [Platform.SENSOR, Platform.BUTTON]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Arranca a integração."""
    from .lib import config as lib_config

    # A sessão, o mapeamento e o histórico ficam no diretório de configuração,
    # para sobreviverem a uma atualização da integração.
    data_dir = hass.config.path(DOMAIN)
    await hass.async_add_executor_job(lib_config.set_data_dir, data_dir)

    coordinator = ContinenteCoordinator(hass, entry)
    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator

    register_views(hass)
    await _async_register_panel(hass)
    _async_register_services(hass)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_reload))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        hass.data[DOMAIN].pop(entry.entry_id, None)
        if not hass.data[DOMAIN]:
            frontend.async_remove_panel(hass, PANEL_URL_PATH)
            for service in (SERVICE_SEND_LIST, SERVICE_ADD_PRODUCT,
                            SERVICE_REMOVE_PRODUCT, SERVICE_SNAPSHOT_PRICES,
                            SERVICE_EMPTY_CART):
                hass.services.async_remove(DOMAIN, service)
    return unloaded


async def _async_reload(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def _async_register_panel(hass: HomeAssistant) -> None:
    """Põe a app de mapeamento na barra lateral.

    O painel é a mesma página da versão autónoma, embebida num iframe e
    servida pela própria integração — daí não precisar de nada externo.
    """
    if PANEL_URL_PATH in hass.data.get("frontend_panels", {}):
        return
    await panel_custom.async_register_panel(
        hass,
        frontend_url_path=PANEL_URL_PATH,
        webcomponent_name="iframe-panel",
        sidebar_title=PANEL_TITLE,
        sidebar_icon=PANEL_ICON,
        module_url=None,
        embed_iframe=True,
        trust_external=False,
        config={"url": f"{API_BASE}/panel/app.html"},
        require_admin=True,
    )


def _async_register_services(hass: HomeAssistant) -> None:
    """Serviços para usar em automações."""

    def first_coordinator() -> ContinenteCoordinator:
        return next(iter(hass.data[DOMAIN].values()))

    async def send_list(call: ServiceCall) -> None:
        result = await first_coordinator().async_send_list(
            mark_done=call.data.get("marcar_no_cookidoo", True)
        )
        _LOGGER.info("enviados %s, falharam %s", result["added"], result["failed"])

    async def add_product(call: ServiceCall) -> None:
        await first_coordinator().async_add_product(
            call.data["produto"], call.data.get("quantidade", 1)
        )

    async def remove_product(call: ServiceCall) -> None:
        await first_coordinator().async_remove_product(call.data["produto"])

    async def snapshot_prices(call: ServiceCall) -> None:
        result = await first_coordinator().async_snapshot_prices()
        _LOGGER.info("%s preços registados", result["recorded"])

    async def empty_cart(call: ServiceCall) -> None:
        await first_coordinator().async_empty_cart()

    hass.services.async_register(
        DOMAIN, SERVICE_SEND_LIST, send_list,
        schema=vol.Schema({vol.Optional("marcar_no_cookidoo", default=True): cv.boolean}),
    )
    hass.services.async_register(
        DOMAIN, SERVICE_ADD_PRODUCT, add_product,
        schema=vol.Schema({
            vol.Required("produto"): cv.string,
            vol.Optional("quantidade", default=1): vol.Coerce(float),
        }),
    )
    hass.services.async_register(
        DOMAIN, SERVICE_REMOVE_PRODUCT, remove_product,
        schema=vol.Schema({vol.Required("produto"): cv.string}),
    )
    hass.services.async_register(DOMAIN, SERVICE_SNAPSHOT_PRICES, snapshot_prices)
    hass.services.async_register(DOMAIN, SERVICE_EMPTY_CART, empty_cart)
