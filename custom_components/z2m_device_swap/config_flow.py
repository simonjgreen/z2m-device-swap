"""Configure a Zigbee2MQTT base topic; no additional credentials."""
import probatio as vol
from homeassistant import config_entries
from .const import BASE_TOPIC, DEFAULT_BASE_TOPIC, DOMAIN


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input=None):
        errors = {}
        if user_input is not None:
            topic = user_input[BASE_TOPIC].strip().rstrip('/')
            if not topic or any(char in topic for char in ('#', '+', '\x00')):
                errors[BASE_TOPIC] = 'invalid_topic'
            else:
                await self.async_set_unique_id(topic)
                self._abort_if_unique_id_configured()
                return self.async_create_entry(title=f'Device Swap ({topic})', data={BASE_TOPIC: topic})
        return self.async_show_form(step_id='user', data_schema=vol.Schema({
            vol.Required(BASE_TOPIC, default=DEFAULT_BASE_TOPIC): str}), errors=errors)
