"""The ten tested control operations, presented as one standard HA fan."""

import math

from homeassistant.components.fan import FanEntity, FanEntityFeature
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.util.percentage import ranged_value_to_percentage

from .entity import AirProceEntity
from .proxy import ControlError


async def async_setup_entry(hass, entry, async_add_entities) -> None:
    async_add_entities([AirProceFan(entry.runtime_data)])


class AirProceFan(AirProceEntity, FanEntity):
    _attr_name = None
    _attr_translation_key = "purifier"
    _attr_icon = "mdi:air-purifier"
    _attr_speed_count = 6
    _attr_preset_modes = ["smart", "sleep"]
    _attr_supported_features = (
        FanEntityFeature.TURN_ON
        | FanEntityFeature.TURN_OFF
        | FanEntityFeature.SET_SPEED
        | FanEntityFeature.PRESET_MODE
    )

    def __init__(self, runtime) -> None:
        super().__init__(runtime, "fan")

    @property
    def is_on(self):
        return self.state_data.power if self.state_data else None

    @property
    def percentage(self):
        state = self.state_data
        if state is None:
            return None
        if not state.power:
            return 0
        return ranged_value_to_percentage((1, 6), state.speed) if state.speed else None

    @property
    def preset_mode(self):
        if not self.state_data or not self.state_data.power:
            return None
        return {"auto": "smart", "sleep": "sleep"}.get(self.state_data.mode)

    async def _execute(self, name):
        try:
            await self.runtime.proxy.execute(name)
        except (ControlError, OSError, TimeoutError, ValueError) as err:
            raise HomeAssistantError(str(err)) from err

    async def async_set_percentage(self, percentage: int) -> None:
        if not 0 <= percentage <= 100:
            raise ServiceValidationError("Percentage must be between 0 and 100")
        await self._execute(f"fan_{math.ceil(percentage * 6 / 100)}" if percentage else "power_off")

    async def async_set_preset_mode(self, preset_mode: str) -> None:
        if preset_mode not in self._attr_preset_modes:
            raise ServiceValidationError("Supported presets are smart and sleep")
        await self._execute("auto" if preset_mode == "smart" else "sleep")

    async def async_turn_on(self, percentage=None, preset_mode=None, **kwargs) -> None:
        if preset_mode is not None:
            await self.async_set_preset_mode(preset_mode)
        elif percentage is not None:
            await self.async_set_percentage(percentage)
        else:
            await self._execute("power_on")

    async def async_turn_off(self, **kwargs) -> None:
        await self._execute("power_off")
