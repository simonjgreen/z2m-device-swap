import asyncio
import importlib.util
from pathlib import Path
import unittest


def module(name):
    path = Path(__file__).parents[1] / f'custom_components/z2m_device_swap/{name}.py'
    spec = importlib.util.spec_from_file_location(name, path)
    loaded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loaded)
    return loaded


class RPCTests(unittest.IsolatedAsyncioTestCase):
    async def test_only_matching_operation_and_transaction_resolves_request(self):
        published = []
        async def publish(topic, payload):
            published.append((topic, payload))
        rpc = module('rpc').RPC(publish, 'zigbee2mqtt', timeout=.05)
        task = asyncio.create_task(rpc.request('device/rename', {'to': 'Kitchen'}))
        await asyncio.sleep(0)
        payload = published[0][1]
        self.assertEqual(published[0][0], 'zigbee2mqtt/bridge/request/device/rename')
        rpc.receive('device/remove', {'transaction': payload['transaction'], 'status':'ok'})
        rpc.receive('device/rename', {'transaction': 'unrelated', 'status':'ok'})
        self.assertFalse(task.done())
        rpc.receive('device/rename', {'transaction': payload['transaction'], 'status':'ok', 'data': {'to':'Kitchen'}})
        self.assertEqual(await task, {'to':'Kitchen'})
        self.assertEqual(rpc.pending, {})

    async def test_timeout_cleans_up_and_does_not_retry(self):
        calls = []
        async def publish(topic, payload):
            calls.append(topic)
        rpc = module('rpc').RPC(publish, 'zigbee2mqtt', timeout=.001)
        with self.assertRaises(TimeoutError):
            await rpc.request('device/remove', {'id': 'old'})
        self.assertEqual(len(calls), 1)
        self.assertEqual(rpc.pending, {})

    async def test_bridge_error_is_not_success(self):
        rpc = None
        async def publish(topic, payload):
            rpc.receive('device/remove', {'transaction': payload['transaction'], 'status': 'error', 'error': 'Device busy'})
        rpc = module('rpc').RPC(publish, 'zigbee2mqtt')
        with self.assertRaisesRegex(ValueError, 'Device busy'):
            await rpc.request('device/remove', {'id': 'old'})


class MappingTests(unittest.TestCase):
    def test_preserve_exact_entity_id_including_suffix(self):
        plan = module('mapping').entity_mapping([
            {'entity_id':'light.kitchen_1_2', 'unique_id':'old_light_zigbee2mqtt', 'domain':'light'}],
            [{'entity_id':'light.kitchen_1','unique_id':'new_light_zigbee2mqtt','domain':'light'}], 'old', 'new')
        self.assertEqual(plan, [('light.kitchen_1', 'light.kitchen_1_2')])

    def test_missing_entity_blocks_entire_mapping(self):
        with self.assertRaisesRegex(ValueError, 'Missing'):
            module('mapping').entity_mapping([{'entity_id':'light.old','unique_id':'old_light_zigbee2mqtt','domain':'light'}], [], 'old', 'new')

    def test_unexpected_unique_id_is_not_guessed(self):
        with self.assertRaises(ValueError):
            module('mapping').entity_mapping([{'entity_id':'light.old','unique_id':'random','domain':'light'}], [], 'old', 'new')

class IdentificationTests(unittest.TestCase):
    def test_native_identify_button_is_preferred(self):
        command=module('mapping').identify_service([
            {'domain':'light','entity_id':'light.kitchen_1_2','unique_id':'old_light_zigbee2mqtt'},
            {'domain':'button','entity_id':'button.kitchen_1_identify','unique_id':'old_identify_zigbee2mqtt','disabled_by':None}
        ],{'light.kitchen_1_2':['blink']})
        self.assertEqual(command,('button','press',{'entity_id':'button.kitchen_1_identify'}))

    def test_blink_effect_is_used_when_no_identify_button_exists(self):
        command=module('mapping').identify_service([
            {'domain':'light','entity_id':'light.kitchen_1_2','unique_id':'old_light_zigbee2mqtt'}
        ],{'light.kitchen_1_2':['blink']})
        self.assertEqual(command,('light','turn_on',{'entity_id':'light.kitchen_1_2','effect':'blink'}))

    def test_disabled_identify_is_not_pressed(self):
        with self.assertRaises(ValueError):
            module('mapping').identify_service([
                {'domain':'button','entity_id':'button.kitchen_1_identify','unique_id':'old_identify_zigbee2mqtt','disabled_by':'user'}
            ],{})

    def test_unrelated_buttons_and_unsupported_lights_are_not_guessed(self):
        with self.assertRaises(ValueError):
            module('mapping').identify_service([
                {'domain':'button','entity_id':'button.restart','unique_id':'old_restart_zigbee2mqtt'},
                {'domain':'light','entity_id':'light.kitchen_1','unique_id':'old_light_zigbee2mqtt'}
            ],{'light.kitchen_1':['candle']})

class LegacyEntityTests(unittest.TestCase):
    def test_disabled_legacy_entities_are_reported_not_required(self):
        old=[
            {'entity_id':'light.kitchen_8_2','domain':'light','unique_id':'old_light_zigbee2mqtt','disabled_by':None},
            {'entity_id':'sensor.kitchen_8_power_on_behavior','domain':'sensor','unique_id':'old_power_on_behavior_zigbee2mqtt','disabled_by':'integration'},
            {'entity_id':'select.kitchen_8_power_on_behavior','domain':'select','unique_id':'old_power_on_behavior_zigbee2mqtt','disabled_by':None},
            {'entity_id':'sensor.kitchen_8_update_state','domain':'sensor','unique_id':'old_update_state_zigbee2mqtt','disabled_by':'integration'},
            {'entity_id':'binary_sensor.kitchen_8_update_available','domain':'binary_sensor','unique_id':'old_update_available_zigbee2mqtt','disabled_by':'integration'},
            {'entity_id':'update.kitchen_8','domain':'update','unique_id':'old_update_zigbee2mqtt','disabled_by':None}]
        new=[{'entity_id':'light.new','domain':'light','unique_id':'new_light_zigbee2mqtt'},
             {'entity_id':'select.new_power_on_behavior','domain':'select','unique_id':'new_power_on_behavior_zigbee2mqtt'},
             {'entity_id':'update.new','domain':'update','unique_id':'new_update_zigbee2mqtt'}]
        plan=module('mapping').replacement_entity_plan(old,new,'old','new')
        self.assertEqual(plan['mappings'],[('light.new','light.kitchen_8_2'),('select.new_power_on_behavior','select.kitchen_8_power_on_behavior'),('update.new','update.kitchen_8')])
        self.assertEqual([e['entity_id'] for e in plan['skipped']],['sensor.kitchen_8_power_on_behavior','sensor.kitchen_8_update_state','binary_sensor.kitchen_8_update_available'])

    def test_enabled_missing_sensor_still_blocks(self):
        with self.assertRaisesRegex(ValueError,'Missing'):
            module('mapping').entity_mapping([{'entity_id':'sensor.used','domain':'sensor','unique_id':'old_power_zigbee2mqtt','disabled_by':None}],[],'old','new')

    def test_disabled_main_light_is_still_required(self):
        with self.assertRaisesRegex(ValueError,'Missing'):
            module('mapping').entity_mapping([{'entity_id':'light.kitchen','domain':'light','unique_id':'old_light_zigbee2mqtt','disabled_by':'user'}],[],'old','new')
