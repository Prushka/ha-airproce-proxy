"""Diagnostics without device addresses, MACs, payloads, or credentials."""


async def async_get_config_entry_diagnostics(hass, entry):
    proxy = entry.runtime_data.proxy
    return {
        "model": entry.data["model"],
        "local_available": proxy.available,
        "device_connected": proxy.session is not None,
        "cloud_connected": proxy.cloud_connected,
        "cloud_registered": proxy.session.cloud_registered if proxy.session else False,
        "cloud_queued_bytes": proxy.session._outgoing.size if proxy.session else 0,
    }
