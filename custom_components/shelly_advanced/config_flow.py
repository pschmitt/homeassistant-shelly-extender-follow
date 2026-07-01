"""Config and options flow for the Shelly Advanced integration."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import (
    SOURCE_IMPORT,
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import CONF_HOST
from homeassistant.core import callback
from homeassistant.helpers import selector
from homeassistant.helpers.service_info.zeroconf import ZeroconfServiceInfo

from .api import ShellyRpc
from .const import (
    CONF_CLIENT_DIRECT_HOST,
    CONF_CLIENT_ENTRY_ID,
    CONF_DIRECT_PORT,
    CONF_EXTENDER_HOST,
    CONF_SCAN_INTERVAL,
    CONF_SELECTED_CLIENTS,
    DEFAULT_DIRECT_PORT,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    MIN_SCAN_INTERVAL,
    SHELLY_DOMAIN,
)

_HEX = set("0123456789abcdef")


def _normalize_mac(mac: str | None) -> str:
    """Reduce any MAC representation to lowercase hex with no separators."""
    return "".join(c for c in (mac or "").lower() if c in _HEX)


def _mac_from_zeroconf_name(name: str) -> str:
    """Extract the 12-hex MAC from a Shelly mDNS name (``model-<mac>._shelly…``)."""
    label = name.split(".")[0]
    tail = label.rsplit("-", 1)[-1].lower()
    return tail if len(tail) == 12 and set(tail) <= _HEX else ""


class ShellyAdvancedConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the initial setup."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize discovery state."""
        self._discovered_client_id: str | None = None
        self._discovered_host: str | None = None
        self._discovered_title: str | None = None

    def _followed_client_ids(self) -> set[str]:
        """Return client entry ids already covered by an existing follow entry."""
        return {
            entry.data.get(CONF_CLIENT_ENTRY_ID)
            for entry in self._async_current_entries()
        }

    def _unfollowed_shellies(self) -> list[ConfigEntry]:
        """Return usable Shelly entries not yet being followed."""
        followed = self._followed_client_ids()
        return [
            entry
            for entry in self.hass.config_entries.async_entries(SHELLY_DOMAIN)
            if entry.entry_id not in followed and entry.unique_id
        ]

    async def async_step_user(
        self, user_input: dict | None = None
    ) -> ConfigFlowResult:
        """Offer manual (single) or bulk discovery."""
        return self.async_show_menu(
            step_id="user", menu_options=["manual", "discover"]
        )

    def _shelly_entry_for_mac(self, mac: str) -> ConfigEntry | None:
        """Return the `shelly` config entry whose MAC matches, if any."""
        return next(
            (
                entry
                for entry in self.hass.config_entries.async_entries(SHELLY_DOMAIN)
                if _normalize_mac(entry.unique_id) == mac
            ),
            None,
        )

    async def async_step_zeroconf(
        self, discovery_info: ZeroconfServiceInfo
    ) -> ConfigFlowResult:
        """Surface a Shelly found on the network as a discovered device.

        We follow an existing `shelly` config entry, so match the advertised
        MAC to one; if none exists (HA doesn't manage this Shelly) there is
        nothing for us to follow.
        """
        mac = _mac_from_zeroconf_name(discovery_info.name)
        if not mac:
            return self.async_abort(reason="no_mac")
        client = self._shelly_entry_for_mac(mac)
        if client is None:
            return self.async_abort(reason="no_shelly_entry")

        await self.async_set_unique_id(client.entry_id)
        self._abort_if_unique_id_configured()

        self._discovered_client_id = client.entry_id
        self._discovered_host = client.data.get(CONF_HOST) or discovery_info.host
        self._discovered_title = client.title
        self.context["title_placeholders"] = {"name": client.title}
        return await self.async_step_discovery_confirm()

    async def async_step_discovery_confirm(
        self, user_input: dict | None = None
    ) -> ConfigFlowResult:
        """Confirm adding a discovered Shelly (extender auto-detected)."""
        if user_input is not None:
            return self.async_create_entry(
                title=f"Follow: {self._discovered_title}",
                data={
                    CONF_CLIENT_ENTRY_ID: self._discovered_client_id,
                    CONF_CLIENT_DIRECT_HOST: self._discovered_host,
                    CONF_EXTENDER_HOST: (
                        user_input.get(CONF_EXTENDER_HOST) or ""
                    ).strip(),
                },
            )
        return self.async_show_form(
            step_id="discovery_confirm",
            description_placeholders={"name": self._discovered_title},
            data_schema=vol.Schema(
                {vol.Optional(CONF_EXTENDER_HOST, default=""): str}
            ),
        )

    async def async_step_manual(
        self, user_input: dict | None = None
    ) -> ConfigFlowResult:
        """Add a single Shelly, specifying its hosts explicitly."""
        errors: dict[str, str] = {}

        if user_input is not None:
            client_entry_id = user_input[CONF_CLIENT_ENTRY_ID]
            client = self.hass.config_entries.async_get_entry(client_entry_id)
            extender = (user_input.get(CONF_EXTENDER_HOST) or "").strip()
            if client is None or not client.unique_id:
                errors["base"] = "invalid_client"
            else:
                await self.async_set_unique_id(client_entry_id)
                self._abort_if_unique_id_configured()
                # Only validate the extender when one was given (it is optional
                # — a Shelly that never roams needs no extender).
                rpc = ShellyRpc(self.hass)
                if extender and await rpc.ap_clients(extender) is None:
                    errors["base"] = "cannot_connect_extender"
                else:
                    return self.async_create_entry(
                        title=f"Follow: {client.title}",
                        data={
                            CONF_CLIENT_ENTRY_ID: client_entry_id,
                            CONF_CLIENT_DIRECT_HOST: user_input[
                                CONF_CLIENT_DIRECT_HOST
                            ],
                            CONF_EXTENDER_HOST: extender,
                        },
                    )

        # A config_entry selector is not rendered by the HA frontend, so build
        # a plain dropdown of the un-followed Shelly entries instead.
        options = [
            selector.SelectOptionDict(value=entry.entry_id, label=entry.title)
            for entry in self._unfollowed_shellies()
        ]
        schema = vol.Schema(
            {
                vol.Required(CONF_CLIENT_ENTRY_ID): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=options,
                        mode=selector.SelectSelectorMode.DROPDOWN,
                    )
                ),
                vol.Required(CONF_CLIENT_DIRECT_HOST): str,
                vol.Optional(CONF_EXTENDER_HOST, default=""): str,
            }
        )
        return self.async_show_form(
            step_id="manual", data_schema=schema, errors=errors
        )

    async def async_step_discover(
        self, user_input: dict | None = None
    ) -> ConfigFlowResult:
        """Bulk-add follow entries for many Shellies at once.

        The direct host defaults to each Shelly entry's current host; an
        optional shared extender host applies to all of them. Fine-tune any
        individual entry afterwards via its options.
        """
        unfollowed = self._unfollowed_shellies()
        if not unfollowed:
            return self.async_abort(reason="no_new_shellies")

        if user_input is not None:
            selected: list[str] = user_input[CONF_SELECTED_CLIENTS]
            extender = (user_input.get(CONF_EXTENDER_HOST) or "").strip()
            payloads = []
            for entry_id in selected:
                client = self.hass.config_entries.async_get_entry(entry_id)
                if client is None or not client.unique_id:
                    continue
                payloads.append(
                    {
                        CONF_CLIENT_ENTRY_ID: entry_id,
                        CONF_CLIENT_DIRECT_HOST: client.data.get(CONF_HOST) or "",
                        CONF_EXTENDER_HOST: extender,
                    }
                )
            if not payloads:
                return self.async_abort(reason="no_new_shellies")

            # Create the remaining entries via import flows; finish this flow
            # by creating the first (a config flow yields a single entry).
            for payload in payloads[1:]:
                self.hass.async_create_task(
                    self.hass.config_entries.flow.async_init(
                        DOMAIN, context={"source": SOURCE_IMPORT}, data=payload
                    )
                )
            first = payloads[0]
            await self.async_set_unique_id(first[CONF_CLIENT_ENTRY_ID])
            self._abort_if_unique_id_configured()
            client = self.hass.config_entries.async_get_entry(
                first[CONF_CLIENT_ENTRY_ID]
            )
            return self.async_create_entry(
                title=f"Follow: {client.title}", data=first
            )

        options = [
            selector.SelectOptionDict(value=entry.entry_id, label=entry.title)
            for entry in unfollowed
        ]
        schema = vol.Schema(
            {
                vol.Required(
                    CONF_SELECTED_CLIENTS,
                    default=[entry.entry_id for entry in unfollowed],
                ): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=options,
                        multiple=True,
                        mode=selector.SelectSelectorMode.LIST,
                    )
                ),
                vol.Optional(CONF_EXTENDER_HOST, default=""): str,
            }
        )
        return self.async_show_form(step_id="discover", data_schema=schema)

    async def async_step_import(
        self, data: dict[str, Any]
    ) -> ConfigFlowResult:
        """Create a follow entry programmatically (used by bulk discovery)."""
        await self.async_set_unique_id(data[CONF_CLIENT_ENTRY_ID])
        self._abort_if_unique_id_configured()
        client = self.hass.config_entries.async_get_entry(
            data[CONF_CLIENT_ENTRY_ID]
        )
        title = f"Follow: {client.title}" if client else data[CONF_CLIENT_ENTRY_ID]
        return self.async_create_entry(title=title, data=data)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        """Return the options flow."""
        return ShellyAdvancedOptionsFlow()


class ShellyAdvancedOptionsFlow(OptionsFlow):
    """Tune the poll interval and direct port."""

    async def async_step_init(
        self, user_input: dict | None = None
    ) -> ConfigFlowResult:
        """Show and persist the options."""
        if user_input is not None:
            # Preserve options not shown here (e.g. follow_enabled, which is
            # owned by the per-entry switch) so saving does not reset them.
            return self.async_create_entry(
                data={**self.config_entry.options, **user_input}
            )

        opts = self.config_entry.options
        schema = vol.Schema(
            {
                vol.Optional(
                    CONF_SCAN_INTERVAL,
                    default=opts.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
                ): vol.All(vol.Coerce(int), vol.Range(min=MIN_SCAN_INTERVAL)),
                vol.Optional(
                    CONF_DIRECT_PORT,
                    default=opts.get(CONF_DIRECT_PORT, DEFAULT_DIRECT_PORT),
                ): vol.All(vol.Coerce(int), vol.Range(min=1, max=65535)),
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)
