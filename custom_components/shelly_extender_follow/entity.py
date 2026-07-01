"""Shared entity base for the Shelly Extender Follow integration."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.device_registry import (
    DeviceEntryType,
    DeviceInfo,
)
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_CLIENT_ENTRY_ID, DOMAIN
from .coordinator import ShellyExtenderFollowCoordinator


def _client_device_info(
    hass: HomeAssistant,
    entry: ConfigEntry,
    client_mac: str,
) -> DeviceInfo:
    """Attach our entities to the client Shelly's existing device.

    Rather than spawning a standalone service device, we reference the Shelly
    device directly so our sensor + switch show up on its device page and the
    device lists both integrations (as openwrt_ubus does via the MAC
    connection). We copy the Shelly device's exact identifiers/connections from
    the registry when it exists (no guessing), and otherwise fall back to
    matching by MAC connection so HA merges us in once the device appears.
    """
    client_entry_id = entry.data[CONF_CLIENT_ENTRY_ID]
    dev_reg = dr.async_get(hass)
    device = next(
        (
            d
            for d in dev_reg.devices.values()
            if client_entry_id in d.config_entries
            and (d.identifiers or d.connections)
        ),
        None,
    )
    if device is not None:
        return DeviceInfo(
            identifiers=set(device.identifiers),
            connections=set(device.connections),
        )
    if client_mac:
        return DeviceInfo(
            connections={(dr.CONNECTION_NETWORK_MAC, dr.format_mac(client_mac))}
        )
    # Last resort: our own service device (should not normally happen).
    return DeviceInfo(
        identifiers={(DOMAIN, entry.entry_id)},
        name=entry.title,
        manufacturer="pschmitt",
        entry_type=DeviceEntryType.SERVICE,
    )


class ShellyExtenderFollowEntity(
    CoordinatorEntity[ShellyExtenderFollowCoordinator]
):
    """Base entity attached to the client Shelly's device."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: ShellyExtenderFollowCoordinator,
        entry: ConfigEntry,
    ) -> None:
        """Initialize the entity."""
        super().__init__(coordinator)
        self._entry = entry
        client_mac = coordinator.data.client_mac if coordinator.data else None
        self._attr_device_info = _client_device_info(
            coordinator.hass, entry, client_mac or ""
        )
