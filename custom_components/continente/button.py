"""Botões: enviar a lista, registar preços, esvaziar o carrinho."""
from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import ContinenteCoordinator


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, add: AddEntitiesCallback
) -> None:
    coordinator: ContinenteCoordinator = hass.data[DOMAIN][entry.entry_id]
    add([
        SendListButton(coordinator),
        SnapshotPricesButton(coordinator),
        EmptyCartButton(coordinator),
    ])


class _Base(CoordinatorEntity[ContinenteCoordinator], ButtonEntity):
    _attr_has_entity_name = True

    def __init__(self, coordinator: ContinenteCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.entry.entry_id)},
            name="Continente",
            manufacturer="Continente",
            entry_type=DeviceEntryType.SERVICE,
        )


class SendListButton(_Base):
    _attr_name = "Enviar lista para o carrinho"
    _attr_icon = "mdi:cart-arrow-down"

    @property
    def unique_id(self) -> str:
        return f"{self.coordinator.entry.entry_id}_send_list"

    async def async_press(self) -> None:
        await self.coordinator.async_send_list()


class SnapshotPricesButton(_Base):
    _attr_name = "Registar preços de hoje"
    _attr_icon = "mdi:chart-line"

    @property
    def unique_id(self) -> str:
        return f"{self.coordinator.entry.entry_id}_snapshot"

    async def async_press(self) -> None:
        await self.coordinator.async_snapshot_prices()


class EmptyCartButton(_Base):
    _attr_name = "Esvaziar carrinho"
    _attr_icon = "mdi:cart-remove"

    @property
    def unique_id(self) -> str:
        return f"{self.coordinator.entry.entry_id}_empty_cart"

    async def async_press(self) -> None:
        await self.coordinator.async_empty_cart()
