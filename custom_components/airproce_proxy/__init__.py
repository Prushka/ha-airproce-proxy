"""AirProce's local TCP proxy integration.

Home Assistant imports stay inside lifecycle functions so the transport can also
be tested with real TCP peers independently of a running Home Assistant instance.
"""

from .const import PLATFORMS
from .runtime import Runtime


async def async_setup_entry(hass, entry) -> bool:
    """Bind only the configured local port; no login or provisioning calls."""
    from homeassistant.const import EVENT_HOMEASSISTANT_STOP
    from homeassistant.exceptions import ConfigEntryNotReady

    runtime = Runtime(dict(entry.data))
    try:
        await runtime.proxy.start()
    except OSError as err:
        raise ConfigEntryNotReady("Unable to bind the configured proxy address/port") from err
    entry.runtime_data = runtime

    async def stop(_event):
        await runtime.proxy.stop()

    entry.async_on_unload(hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, stop))
    try:
        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    except BaseException:
        await runtime.proxy.stop()
        raise
    return True


async def async_unload_entry(hass, entry) -> bool:
    """Release the listener and every device/upstream task."""
    if await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        await entry.runtime_data.proxy.stop()
        return True
    return False
