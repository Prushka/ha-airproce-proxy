"""Match the existing integration's four locally verified measurements."""

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import PERCENTAGE, UnitOfDensity, UnitOfTemperature

from .entity import AirProceEntity

DESCRIPTIONS = (
    SensorEntityDescription(
        key="temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        suggested_display_precision=1,
    ),
    SensorEntityDescription(
        key="humidity",
        device_class=SensorDeviceClass.HUMIDITY,
        native_unit_of_measurement=PERCENTAGE,
        suggested_display_precision=1,
    ),
    SensorEntityDescription(
        key="pm25",
        device_class=SensorDeviceClass.PM25,
        native_unit_of_measurement=UnitOfDensity.MICROGRAMS_PER_CUBIC_METER,
        suggested_display_precision=0,
    ),
    SensorEntityDescription(
        key="voc",
        device_class=SensorDeviceClass.VOLATILE_ORGANIC_COMPOUNDS,
        native_unit_of_measurement=UnitOfDensity.MILLIGRAMS_PER_CUBIC_METER,
        suggested_display_precision=3,
    ),
)


async def async_setup_entry(hass, entry, async_add_entities) -> None:
    async_add_entities(AirProceSensor(entry.runtime_data, desc) for desc in DESCRIPTIONS)


class AirProceSensor(AirProceEntity, SensorEntity):
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, runtime, description) -> None:
        super().__init__(runtime, "temp" if description.key == "temperature" else description.key)
        self.entity_description = description

    @property
    def native_value(self):
        return getattr(self.state_data, self.entity_description.key) if self.state_data else None
