"""Configuração pela interface: credenciais do Continente e do Cookidoo."""
from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry, ConfigFlow, OptionsFlow
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult

from .const import (
    CONF_CONTINENTE_EMAIL,
    CONF_CONTINENTE_PASSWORD,
    CONF_COOKIDOO_EMAIL,
    CONF_COOKIDOO_PASSWORD,
    CONF_SCAN_MINUTES,
    DEFAULT_SCAN_MINUTES,
    DOMAIN,
)

SCHEMA = vol.Schema({
    vol.Required(CONF_CONTINENTE_EMAIL): str,
    vol.Required(CONF_CONTINENTE_PASSWORD): str,
    vol.Optional(CONF_COOKIDOO_EMAIL, default=""): str,
    vol.Optional(CONF_COOKIDOO_PASSWORD, default=""): str,
})


class ContinenteConfigFlow(ConfigFlow, domain=DOMAIN):
    """Pede as credenciais e confirma que servem antes de guardar."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            await self.async_set_unique_id(user_input[CONF_CONTINENTE_EMAIL].lower())
            self._abort_if_unique_id_configured()

            error = await self.hass.async_add_executor_job(
                _check_credentials, self.hass.config.path(DOMAIN), user_input
            )
            if error:
                errors["base"] = error
            else:
                return self.async_create_entry(
                    title=user_input[CONF_CONTINENTE_EMAIL], data=user_input
                )

        return self.async_show_form(
            step_id="user", data_schema=SCHEMA, errors=errors
        )

    @staticmethod
    @callback
    def async_get_options_flow(entry: ConfigEntry) -> OptionsFlow:
        return ContinenteOptionsFlow(entry)


class ContinenteOptionsFlow(OptionsFlow):
    """De quanto em quanto tempo se vai ao site."""

    def __init__(self, entry: ConfigEntry) -> None:
        self.entry = entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema({
                vol.Optional(
                    CONF_SCAN_MINUTES,
                    default=self.entry.options.get(
                        CONF_SCAN_MINUTES, DEFAULT_SCAN_MINUTES),
                ): vol.All(vol.Coerce(int), vol.Range(min=5, max=1440)),
            }),
        )


def _check_credentials(data_dir: str, user_input: dict[str, Any]) -> str | None:
    """Tenta mesmo iniciar sessão. Devolve a chave do erro, ou `None`."""
    from .lib import config as lib_config
    from .lib.login import LoginError, login_http

    lib_config.set_data_dir(data_dir)
    try:
        login_http(
            user_input[CONF_CONTINENTE_EMAIL],
            user_input[CONF_CONTINENTE_PASSWORD],
        )
    except LoginError:
        return "invalid_auth"
    except Exception:  # noqa: BLE001
        return "cannot_connect"

    if not user_input.get(CONF_COOKIDOO_EMAIL):
        return None

    from .lib.cookidoo import CookidooClient, CookidooError

    try:
        CookidooClient(
            user_input[CONF_COOKIDOO_EMAIL],
            user_input[CONF_COOKIDOO_PASSWORD],
        ).shopping_list()
    except CookidooError:
        return "invalid_cookidoo"
    except Exception:  # noqa: BLE001
        return "cannot_connect"
    return None
