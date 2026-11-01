"""Config flow for the Siemens RDF302 integration."""

from collections.abc import Mapping
from typing import Any

from modbus_connection import ModbusError
import voluptuous as vol

from homeassistant.components.modbus import async_get_temporary_unit
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_HOST, CONF_NAME, CONF_PORT
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
)

from . import create_modbus_params
from .const import (
    CONF_APPLICATION,
    CONF_MODEL,
    CONF_UNIT_ID,
    DEFAULT_NAME,
    DEFAULT_PORT,
    DEFAULT_UNIT_ID,
    DOMAIN,
)
from .rdf302_modbus import Application, Model, Rdf302, is_thermostat

APPLICATION_OPTIONS = {
    "two_pipe": Application.TWO_PIPE,
    "two_pipe_3pos": Application.TWO_PIPE_3POS,
    "two_pipe_heater": Application.TWO_PIPE_HEATER,
    "four_pipe": Application.FOUR_PIPE,
}


def _select(key: str, options: list[str]) -> SelectSelector:
    return SelectSelector(
        SelectSelectorConfig(
            options=options,
            mode=SelectSelectorMode.DROPDOWN,
            translation_key=key,
        )
    )


def _number(minimum: int, maximum: int) -> vol.All:
    return vol.All(
        NumberSelector(
            NumberSelectorConfig(min=minimum, max=maximum, mode=NumberSelectorMode.BOX)
        ),
        vol.Coerce(int),
    )


def _link_schema(defaults: Mapping[str, Any]) -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(CONF_HOST, default=defaults.get(CONF_HOST, "")): TextSelector(),
            vol.Required(
                CONF_PORT, default=defaults.get(CONF_PORT, DEFAULT_PORT)
            ): _number(1, 65535),
            vol.Required(
                CONF_UNIT_ID, default=defaults.get(CONF_UNIT_ID, DEFAULT_UNIT_ID)
            ): _number(1, 247),
            vol.Required(
                CONF_MODEL, default=defaults.get(CONF_MODEL, Model.RDF302.value)
            ): _select(CONF_MODEL, [model.value for model in Model]),
        }
    )


USER_SCHEMA_NAME = {vol.Required(CONF_NAME, default=DEFAULT_NAME): TextSelector()}
APPLICATION_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_APPLICATION, default="two_pipe"): _select(
            CONF_APPLICATION, list(APPLICATION_OPTIONS)
        )
    }
)


def _unique_id(data: Mapping[str, Any]) -> str:
    """Return the identity of a thermostat, which has no serial number."""
    return f"{data[CONF_HOST]}:{data[CONF_PORT]}:{data[CONF_UNIT_ID]}"


class Rdf302ConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for a thermostat."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize the flow."""
        self._data: dict[str, Any] = {}

    async def _async_probe(self, data: Mapping[str, Any]) -> tuple[str | None, bool]:
        """Check for a thermostat; return an error and whether it reports its application."""
        try:
            async with async_get_temporary_unit(
                self.hass, create_modbus_params(data), data[CONF_UNIT_ID]
            ) as unit:
                device = Rdf302(unit)
                await device.async_update_fast()
        except ModbusError, OSError:
            return "cannot_connect", False
        except HomeAssistantError:
            return "link_conflict", False
        if not is_thermostat(device.registers):
            return "not_a_thermostat", False
        return None, device.application is not Application.NONE

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask how the thermostat is reached."""
        errors: dict[str, str] = {}
        if user_input is not None:
            await self.async_set_unique_id(_unique_id(user_input))
            self._abort_if_unique_id_configured()
            error, reports_application = await self._async_probe(user_input)
            if error:
                errors["base"] = error
            else:
                self._data = user_input
                if reports_application:
                    return self._async_create()
                return await self.async_step_application()

        schema = _link_schema(user_input or {}).extend(USER_SCHEMA_NAME)
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)

    async def async_step_application(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for the application, which DIP-configured units may not report."""
        if user_input is not None:
            self._data[CONF_APPLICATION] = int(
                APPLICATION_OPTIONS[user_input[CONF_APPLICATION]]
            )
            return self._async_create()
        return self.async_show_form(
            step_id="application", data_schema=APPLICATION_SCHEMA
        )

    def _async_create(self) -> ConfigFlowResult:
        data = dict(self._data)
        return self.async_create_entry(title=data.pop(CONF_NAME), data=data)

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Let the user change how the thermostat is reached."""
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            await self.async_set_unique_id(_unique_id(user_input))
            self._abort_if_unique_id_mismatch_or_configured(entry)
            error, _ = await self._async_probe(user_input)
            if error:
                errors["base"] = error
            else:
                return self.async_update_reload_and_abort(
                    entry,
                    unique_id=_unique_id(user_input),
                    data_updates=user_input,
                )
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=_link_schema(user_input or entry.data),
            errors=errors,
        )

    def _abort_if_unique_id_mismatch_or_configured(self, entry) -> None:
        """Abort if the new address belongs to another entry."""
        if self.unique_id != entry.unique_id:
            self._abort_if_unique_id_configured()
