"""Home Assistant entity snapshots and exact ID restoration."""
import asyncio
from homeassistant.helpers import entity_registry as er
from .mapping import entity_mapping


class Registry:
    def __init__(self, hass, base_topic):
        self.hass = hass
        self.base_topic = base_topic

    def entities(self, ieee):
        registry = er.async_get(self.hass)
        suffix = '_' + self.base_topic
        return [{'entity_id': entry.entity_id, 'unique_id': entry.unique_id,
                 'domain': entry.domain, 'name': entry.name,
                 'icon': entry.icon, 'area_id': entry.area_id,
                 'disabled_by': entry.disabled_by, 'hidden_by': entry.hidden_by}
                for entry in registry.entities.values()
                if entry.platform == 'mqtt' and entry.unique_id.startswith(ieee + '_')
                and entry.unique_id.endswith(suffix)]

    def mapping(self, session):
        return entity_mapping(session['entities'], self.entities(session['replacement']['ieee_address']),
                              session['old']['ieee_address'], session['replacement']['ieee_address'])

    def validate_entities(self, session):
        self.mapping(session)

    async def restore_entities(self, session):
        registry = er.async_get(self.hass)
        # Discovery and removal are asynchronous; give HA time to finish before reporting a collision.
        deadline = asyncio.get_running_loop().time() + 30
        last_error = 'Waiting for MQTT discovery'
        while asyncio.get_running_loop().time() < deadline:
            try:
                mapping = self.mapping(session)
                for source, target in mapping:
                    if source != target and registry.async_get(target) is not None:
                        raise ValueError(f'Entity ID is still occupied: {target}')
                break
            except ValueError as error:
                last_error = str(error)
                await asyncio.sleep(.5)
        else:
            raise ValueError(last_error)
        # All mappings and collisions checked before changing any ID.
        by_target = {e['entity_id']: e for e in session['entities']}
        for source, target in mapping:
            original = by_target[target]
            kwargs = {key: original.get(key) for key in ('name', 'icon', 'area_id', 'disabled_by', 'hidden_by')}
            for key, enum_type in (('disabled_by', er.RegistryEntryDisabler), ('hidden_by', er.RegistryEntryHider)):
                if kwargs[key] is not None:
                    kwargs[key] = enum_type(kwargs[key])
            if source != target:
                kwargs['new_entity_id'] = target
            registry.async_update_entity(source, **kwargs)

    def verify_entities(self, session):
        try:
            return all(source == target for source, target in self.mapping(session))
        except ValueError:
            return False
