"""Sensors for Meraki Data Usage."""
from __future__ import annotations

from homeassistant.components.sensor import (
    SensorDeviceClass, SensorEntity, SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfInformation
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import MerakiUsageCoordinator

GB = 1_000_000_000


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator: MerakiUsageCoordinator = entry.runtime_data
    async_add_entities([
        UsageTodaySensor(coordinator, entry),
        ActiveClientsSensor(coordinator, entry),
    ])


class _Base(CoordinatorEntity[MerakiUsageCoordinator], SensorEntity):
    _attr_has_entity_name = True

    def __init__(self, coordinator: MerakiUsageCoordinator, entry: ConfigEntry, key: str) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.data['network_id']}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.data["network_id"])},
            name="Meraki Data Usage",
            manufacturer="Cisco Meraki",
            model="Dashboard API",
        )


class UsageTodaySensor(_Base):
    """Internet usage since midnight, with the full breakdown in attributes."""

    _attr_name = "Internet usage today"
    _attr_icon = "mdi:chart-sankey"
    _attr_device_class = SensorDeviceClass.DATA_SIZE
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_native_unit_of_measurement = UnitOfInformation.GIGABYTES
    _attr_suggested_display_precision = 2
    _unrecorded_attributes = frozenset(
        {"lines", "devices", "other_devices", "not_broken_down", "since", "updated", "apps_missing"}
    )

    def __init__(self, coordinator, entry) -> None:
        super().__init__(coordinator, entry, "usage_today")

    @property
    def native_value(self):
        data = self.coordinator.data or {}
        return round(data.get("total", 0) / GB, 3)

    @property
    def extra_state_attributes(self):
        d = self.coordinator.data or {}
        return {
            "since": d.get("since"),
            "updated": d.get("updated"),
            "lines": d.get("lines", []),
            "devices": d.get("devices", []),
            "other_devices": d.get("other_devices", {}),
            "not_broken_down": d.get("not_broken_down", 0),
            "apps_missing": d.get("apps_missing", []),
        }


class ActiveClientsSensor(_Base):
    _attr_name = "Clients with traffic today"
    _attr_icon = "mdi:devices"
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator, entry) -> None:
        super().__init__(coordinator, entry, "clients_today")

    @property
    def native_value(self):
        return (self.coordinator.data or {}).get("client_count", 0)
