"""Explicit per-device listener configuration; router rules remain manual."""

import ipaddress
import re
import socket

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback

from .const import DOMAIN, MODELS


def normalize(data: dict) -> dict:
    data = dict(data)
    for key in ("listen_host", "allowed_peer", "purifier_host"):
        address = ipaddress.IPv4Address(data[key].strip())
        if address.is_unspecified or address.is_multicast:
            raise ValueError("An explicit unicast IPv4 address is required")
        data[key] = str(address)
    mac = re.sub(r"[:-]", "", data["mac"]).lower()
    if not re.fullmatch(r"[0-9a-f]{12}", mac):
        raise ValueError("Invalid MAC address")
    data["mac"] = ":".join(mac[i : i + 2] for i in range(0, 12, 2))
    data["name"] = data["name"].strip()
    if not data["name"] or data["model"] not in MODELS:
        raise ValueError("A name and supported model are required")
    if type(data["listen_port"]) is not int or not 1024 <= data["listen_port"] <= 65535:
        raise ValueError("Invalid listener port")
    return data


def schema(defaults=None):
    defaults = defaults or {}
    return vol.Schema(
        {
            vol.Required("name", default=defaults.get("name", "AirProce")): str,
            vol.Required("model", default=defaults.get("model", "AI-600")): vol.In(MODELS),
            vol.Required("mac", default=defaults.get("mac", "")): str,
            vol.Required("purifier_host", default=defaults.get("purifier_host", "")): str,
            vol.Required("listen_host", default=defaults.get("listen_host", "")): str,
            vol.Required("listen_port", default=defaults.get("listen_port", 19001)): vol.All(
                vol.Coerce(int), vol.Range(min=1024, max=65535)
            ),
            vol.Required("allowed_peer", default=defaults.get("allowed_peer", "")): str,
        }
    )


class AirProceProxyConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input=None):
        errors = {}
        if user_input is not None:
            try:
                data = normalize(user_input)
            except ValueError, KeyError:
                errors["base"] = "invalid_config"
            else:
                await self.async_set_unique_id(data["mac"])
                self._abort_if_unique_id_configured()
                if any(
                    entry.data["listen_port"] == data["listen_port"]
                    and entry.data["listen_host"] == data["listen_host"]
                    for entry in self._async_current_entries()
                ):
                    errors["base"] = "port_in_use"
                else:
                    # Binding is local and immediate. Never require a cloud or
                    # purifier connection before the manual router rules exist.
                    try:
                        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
                            probe.bind((data["listen_host"], data["listen_port"]))
                    except OSError:
                        errors["base"] = "cannot_bind"
                    else:
                        return self.async_create_entry(title=data["name"], data=data)
        return self.async_show_form(step_id="user", data_schema=schema(user_input), errors=errors)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return AirProceProxyOptionsFlow()


class AirProceProxyOptionsFlow(config_entries.OptionsFlow):
    async def async_step_init(self, user_input=None):
        errors = {}
        if user_input is not None:
            try:
                data = normalize(user_input)
                if data["mac"] != self.config_entry.data["mac"]:
                    raise ValueError("The physical device identity cannot change")
            except ValueError, KeyError:
                errors["base"] = "invalid_config"
            else:
                others = self.hass.config_entries.async_entries(DOMAIN)
                if any(
                    entry.entry_id != self.config_entry.entry_id
                    and entry.data["listen_port"] == data["listen_port"]
                    and entry.data["listen_host"] == data["listen_host"]
                    for entry in others
                ):
                    errors["base"] = "port_in_use"
                else:
                    self.hass.config_entries.async_update_entry(
                        self.config_entry,
                        title=data["name"],
                        data=data,
                    )
                    await self.hass.config_entries.async_reload(self.config_entry.entry_id)
                    return self.async_create_entry(title="", data={})
        return self.async_show_form(
            step_id="init",
            data_schema=schema(user_input or self.config_entry.data),
            errors=errors,
        )
