"""Common identity and availability for a purifier's five local entities."""

from homeassistant.helpers.device_registry import CONNECTION_NETWORK_MAC
from homeassistant.helpers.entity import DeviceInfo, Entity

from .const import DOMAIN


class AirProceEntity(Entity):
    _attr_should_poll = False
    _attr_has_entity_name = True

    def __init__(self, runtime, suffix) -> None:
        self.runtime = runtime
        data = runtime.data
        self._attr_unique_id = f"{data['mac']}-{suffix}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, data["mac"])},
            # Integration identifiers are separate. The physical MAC deliberately
            # lets HA recognize the same hardware if both integrations coexist.
            connections={(CONNECTION_NETWORK_MAC, data["mac"])},
            manufacturer="AirProce",
            model=data["model"],
            name=data["name"],
        )

    @property
    def available(self) -> bool:
        return self.runtime.proxy.available

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(self.runtime.subscribe(self.async_write_ha_state))

    @property
    def state_data(self):
        return self.runtime.proxy.state
