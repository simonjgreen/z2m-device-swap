"""Run the real registry adapter against an in-memory HA registry boundary."""
import asyncio
from enum import StrEnum
import importlib.util
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import patch

ROOT=Path(__file__).parents[1]/'custom_components/z2m_device_swap'


class Reason(StrEnum):
    USER='user'
    INTEGRATION='integration'


class FakeRegistry:
    def __init__(self):
        self.entities={}
        self.updates=[]
    def add(self, entity_id, unique_id):
        self.entities[entity_id]=SimpleNamespace(entity_id=entity_id,unique_id=unique_id,
            domain=entity_id.split('.')[0],platform='mqtt',name=None,icon=None,area_id=None,
            disabled_by=None,hidden_by=None)
    def async_get(self, entity_id):
        return self.entities.get(entity_id)
    def async_update_entity(self, entity_id, **kwargs):
        self.updates.append((entity_id,kwargs))
        entry=self.entities.pop(entity_id)
        entry.entity_id=kwargs.pop('new_entity_id',entity_id)
        for key,value in kwargs.items(): setattr(entry,key,value)
        self.entities[entry.entity_id]=entry


def load_registry(registry):
    package=ModuleType('registry_test_package');package.__path__=[str(ROOT)]
    hass=ModuleType('homeassistant');helpers=ModuleType('homeassistant.helpers')
    er=ModuleType('homeassistant.helpers.entity_registry')
    er.async_get=lambda hass:registry
    er.RegistryEntryDisabler=Reason;er.RegistryEntryHider=Reason
    helpers.entity_registry=er
    modules={'registry_test_package':package,'homeassistant':hass,'homeassistant.helpers':helpers,
             'homeassistant.helpers.entity_registry':er}
    with patch.dict(sys.modules,modules):
        for name in ('mapping','registry'):
            spec=importlib.util.spec_from_file_location('registry_test_package.'+name,ROOT/(name+'.py'))
            loaded=importlib.util.module_from_spec(spec)
            sys.modules[spec.name]=loaded;spec.loader.exec_module(loaded)
        return loaded.Registry(None,'zigbee2mqtt')


class RegistryTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.registry=FakeRegistry()
        self.registry.add('light.kitchen_1_2','old_light_zigbee2mqtt')
        self.registry.entities['light.kitchen_1_2'].disabled_by=Reason.USER
        self.adapter=load_registry(self.registry)
        self.session={'old':{'ieee_address':'old'},'replacement':{'ieee_address':'new'},
                      'entities':self.adapter.entities('old')}
        self.registry.add('light.replacement','new_light_zigbee2mqtt')

    async def test_restores_exact_id_and_disabled_setting(self):
        self.adapter.validate_entities(self.session)
        self.registry.entities.pop('light.kitchen_1_2')
        await self.adapter.restore_entities(self.session)
        self.assertTrue(self.adapter.verify_entities(self.session))
        self.assertIs(self.registry.async_get('light.kitchen_1_2').disabled_by,Reason.USER)
        self.assertIsNone(self.registry.async_get('light.replacement'))

    async def test_collision_does_not_rename_or_remove_unrelated_entity(self):
        self.registry.entities.pop('light.kitchen_1_2')
        self.registry.add('light.kitchen_1_2','unrelated_light_zigbee2mqtt')
        task=asyncio.create_task(self.adapter.restore_entities(self.session))
        await asyncio.sleep(.01)
        self.assertFalse(task.done())
        self.assertEqual(self.registry.updates,[])
        self.assertEqual(self.registry.async_get('light.kitchen_1_2').unique_id,'unrelated_light_zigbee2mqtt')
        task.cancel()
        with self.assertRaises(asyncio.CancelledError): await task

    async def test_waits_for_old_discovery_removal(self):
        task=asyncio.create_task(self.adapter.restore_entities(self.session))
        await asyncio.sleep(.01)
        self.assertEqual(self.registry.updates,[])
        self.registry.entities.pop('light.kitchen_1_2')
        await task
        self.assertTrue(self.adapter.verify_entities(self.session))

    async def test_roundtrip_persisted_disabled_reason(self):
        self.session['entities'][0]['disabled_by']='user'
        self.registry.entities.pop('light.kitchen_1_2')
        await self.adapter.restore_entities(self.session)
        self.assertIs(self.registry.async_get('light.kitchen_1_2').disabled_by,Reason.USER)
