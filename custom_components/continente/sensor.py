"""Sensores: o carrinho, a lista, e o preço de cada produto seguido."""
from __future__ import annotations

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
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

    entities: list[SensorEntity] = [
        CartTotalSensor(coordinator),
        CartItemsSensor(coordinator),
        ToBuySensor(coordinator),
        UndecidedSensor(coordinator),
    ]
    # Um sensor por produto com histórico: é o que dá gráficos e automações
    # de preço sem esforço nenhum.
    entities += [
        ProductPriceSensor(coordinator, p["pid"], p.get("nome") or p["pid"])
        for p in coordinator.data.get("tracked", [])
    ]
    add(entities)


class _Base(CoordinatorEntity[ContinenteCoordinator], SensorEntity):
    _attr_has_entity_name = True

    def __init__(self, coordinator: ContinenteCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.entry.entry_id)},
            name="Continente",
            manufacturer="Continente",
            entry_type=DeviceEntryType.SERVICE,
        )


class CartTotalSensor(_Base):
    _attr_name = "Total do carrinho"
    _attr_native_unit_of_measurement = "EUR"
    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_icon = "mdi:cart"

    @property
    def unique_id(self) -> str:
        return f"{self.coordinator.entry.entry_id}_cart_total"

    @property
    def native_value(self) -> float | None:
        cart = self.coordinator.data.get("cart") or {}
        total = cart.get("grand_total")
        if not total:
            return None
        return float(str(total).replace("€", "").replace(",", ".").strip())

    @property
    def extra_state_attributes(self) -> dict:
        cart = self.coordinator.data.get("cart") or {}
        return {
            "autenticado": cart.get("authenticated"),
            "produtos": [
                {"nome": i["name"], "quantidade": i["quantity"],
                 "unidade": i["unit"], "total": i["line_total_formatted"]}
                for i in cart.get("items", [])
            ],
        }


class CartItemsSensor(_Base):
    _attr_name = "Artigos no carrinho"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:cart-outline"

    @property
    def unique_id(self) -> str:
        return f"{self.coordinator.entry.entry_id}_cart_items"

    @property
    def native_value(self) -> int:
        return len((self.coordinator.data.get("cart") or {}).get("items", []))


class ToBuySensor(_Base):
    _attr_name = "Por comprar"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:playlist-check"

    @property
    def unique_id(self) -> str:
        return f"{self.coordinator.entry.entry_id}_to_buy"

    @property
    def native_value(self) -> int:
        counts = (self.coordinator.data.get("list") or {}).get("counts") or {}
        return counts.get("a_comprar", 0)

    @property
    def extra_state_attributes(self) -> dict:
        listing = self.coordinator.data.get("list") or {}
        return {
            "itens": [
                {"nome": i["name"], "quantidade": i["amount"],
                 "produto": (i.get("mapped") or {}).get("nome_continente")}
                for i in listing.get("items", [])
                if i["status"] == "mapeado" and not i["owned"]
            ],
            "erro": listing.get("erro"),
        }


class UndecidedSensor(_Base):
    _attr_name = "Por decidir"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:help-circle-outline"

    @property
    def unique_id(self) -> str:
        return f"{self.coordinator.entry.entry_id}_undecided"

    @property
    def native_value(self) -> int:
        counts = (self.coordinator.data.get("list") or {}).get("counts") or {}
        return counts.get("por_decidir", 0)


class ProductPriceSensor(_Base):
    """Preço de um produto seguido, com o histórico a cargo do recorder."""

    _attr_native_unit_of_measurement = "EUR"
    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:tag-outline"

    def __init__(self, coordinator: ContinenteCoordinator, pid: str,
                 name: str) -> None:
        super().__init__(coordinator)
        self._pid = pid
        self._attr_name = f"Preço {name}"

    @property
    def unique_id(self) -> str:
        return f"{self.coordinator.entry.entry_id}_price_{self._pid}"

    def _row(self) -> dict:
        for p in self.coordinator.data.get("tracked", []):
            if p["pid"] == self._pid:
                return p
        return {}

    @property
    def native_value(self) -> float | None:
        return self._row().get("preco")

    @property
    def extra_state_attributes(self) -> dict:
        row = self._row()
        return {
            "pid": self._pid,
            "pvpr": row.get("preco_ref"),
            "minimo_registado": row.get("minimo"),
            "maximo_registado": row.get("maximo"),
            "variacao_pct": row.get("variacao"),
            "dias_registados": row.get("dias"),
        }
