"""Exercise real workflow decisions against a simulated bridge, never production."""
import asyncio
import copy
import importlib.util
from pathlib import Path
import unittest

PATH = Path(__file__).parents[1] / 'custom_components/z2m_device_swap/workflow.py'

def load_workflow():
    spec = importlib.util.spec_from_file_location('workflow', PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.Workflow


def bulb(ieee, name):
    return {'ieee_address': ieee, 'friendly_name': name, 'type': 'Router',
            'interview_completed': True, 'supported': True,
            'definition': {'model': 'GU10', 'exposes': [{'type': 'light', 'features': [
                {'property': 'state'}, {'property': 'brightness'}]}]},
            'endpoints': {'1': {}}}


class Bridge:
    def __init__(self):
        self.devices = {'old': bulb('old', 'Kitchen 1'), 'new': bulb('new', 'Replacement')}
        self.groups = [{'id': 7, 'friendly_name': 'Kitchen', 'members': [
            {'ieee_address': 'old', 'endpoint': 1}]}]
        self.calls = []
        self.fail = None
        self.restore_count = 0

    def entities(self, ieee):
        return [{'entity_id': 'light.custom_kitchen_1', 'unique_id': f'{ieee}_light_zigbee2mqtt',
                 'domain': 'light', 'name': 'My bulb'}]

    async def request(self, operation, payload):
        self.calls.append((operation, copy.deepcopy(payload)))
        if self.fail == operation:
            self.fail = None
            raise TimeoutError('Response lost')
        if operation == 'device/remove':
            del self.devices[payload['id']]
        elif operation == 'device/rename':
            self.devices[payload['from']]['friendly_name'] = payload['to']
        elif operation == 'group/members/add':
            for group in self.groups:
                if group['id'] == payload['group']:
                    group['members'].append({'ieee_address': payload['device'].split('/')[0], 'endpoint': 1})
        return {}

    def validate_entities(self, session):
        pass

    async def restore_entities(self, session):
        self.restore_count += 1

    def verify_entities(self, session):
        return self.restore_count > 0


class WorkflowTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.saved = []
        self.bridge = Bridge()
        async def save(session):
            self.saved.append(copy.deepcopy(session))
        self.save = save
        self.flow = load_workflow()(self.bridge, save)

    async def ready(self):
        await self.flow.begin('old')
        await self.flow.select('new')

    async def test_snapshot_and_review_do_not_mutate_bridge(self):
        await self.ready()
        self.assertEqual(self.bridge.calls, [])
        snapshot = self.flow.snapshot()
        self.assertEqual(snapshot['old']['friendly_name'], 'Kitchen 1')
        self.assertEqual(snapshot['entities'][0]['entity_id'], 'light.custom_kitchen_1')
        self.assertEqual(snapshot['groups'][0]['id'], 7)

    async def test_apply_requires_explicit_confirmation(self):
        await self.ready()
        with self.assertRaises(ValueError):
            await self.flow.apply(False)
        self.assertEqual(self.bridge.calls, [])

    async def test_restore_name_entities_and_groups_then_require_physical_check(self):
        await self.ready()
        await self.flow.apply(True)
        self.assertEqual(self.bridge.devices['new']['friendly_name'], 'Kitchen 1')
        self.assertNotIn('old', self.bridge.devices)
        self.assertTrue(any(m['ieee_address'] == 'new' for m in self.bridge.groups[0]['members']))
        self.assertEqual(self.bridge.restore_count, 1)
        self.assertEqual(self.flow.snapshot()['stage'], 'verify')
        self.assertFalse(self.flow.snapshot()['physical_test_confirmed'])
        await self.flow.finish(True)
        self.assertEqual(self.flow.snapshot()['stage'], 'complete')
        rename = next(p for op, p in self.bridge.calls if op == 'device/rename')
        self.assertIs(rename['homeassistant_rename'], True)

    async def test_intent_saved_before_removal(self):
        await self.ready()
        original = self.bridge.request
        async def check(operation, payload):
            if operation == 'device/remove':
                self.assertEqual(self.saved[-1]['pending'], 'remove')
            return await original(operation, payload)
        self.bridge.request = check
        await self.flow.apply(True)

    async def test_reject_incompatible_replacement_without_removal(self):
        await self.flow.begin('old')
        self.bridge.devices['new']['definition']['exposes'][0]['features'] = [{'property': 'state'}]
        with self.assertRaises(ValueError):
            await self.flow.select('new')
        self.assertEqual(self.bridge.calls, [])

    async def test_reject_same_device(self):
        await self.flow.begin('old')
        with self.assertRaises(ValueError):
            await self.flow.select('old')

    async def test_reject_unfinished_interview(self):
        await self.flow.begin('old')
        self.bridge.devices['new']['interview_completed'] = False
        with self.assertRaises(ValueError):
            await self.flow.select('new')

    async def test_recheck_compatibility_at_apply(self):
        await self.ready()
        self.bridge.devices['new']['definition']['exposes'] = []
        with self.assertRaises(ValueError):
            await self.flow.apply(True)
        self.assertEqual(self.bridge.calls, [])

    async def test_group_failure_keeps_snapshot_and_resume_skips_removed_device(self):
        await self.ready()
        self.bridge.fail = 'group/members/add'
        with self.assertRaises(TimeoutError):
            await self.flow.apply(True)
        self.assertEqual(self.flow.snapshot()['stage'], 'attention')
        restored = load_workflow()(self.bridge, self.save, self.saved[-1])
        await restored.apply(True)
        self.assertEqual(sum(op == 'device/remove' for op, _ in self.bridge.calls), 1)
        self.assertEqual(restored.snapshot()['stage'], 'verify')
        self.assertEqual(restored.snapshot()['entities'][0]['entity_id'], 'light.custom_kitchen_1')

    async def test_lost_remove_response_with_device_absent_resumes_without_duplicate_removal(self):
        await self.ready()
        original = self.bridge.request
        async def lost(operation, payload):
            result = await original(operation, payload)
            if operation == 'device/remove':
                self.bridge.request = original
                raise TimeoutError('response lost after removal')
            return result
        self.bridge.request = lost
        with self.assertRaises(TimeoutError):
            await self.flow.apply(True)
        await self.flow.apply(True)
        self.assertEqual(sum(op == 'device/remove' for op, _ in self.bridge.calls), 1)

    async def test_snapshot_is_defensive_copy(self):
        await self.flow.begin('old')
        self.flow.snapshot()['old']['friendly_name'] = 'Changed'
        self.assertEqual(self.flow.snapshot()['old']['friendly_name'], 'Kitchen 1')

    async def test_begin_cannot_overwrite_active_swap(self):
        await self.ready()
        with self.assertRaises(ValueError):
            await self.flow.begin('new')
        self.assertEqual(self.flow.snapshot()['old']['ieee_address'], 'old')

    async def test_no_completed_state_without_registry_verification(self):
        await self.ready()
        self.bridge.verify_entities = lambda session: False
        with self.assertRaises(ValueError):
            await self.flow.apply(True)
        self.assertEqual(self.flow.snapshot()['stage'], 'attention')

    async def test_group_endpoint_mismatch_stops_before_deletion(self):
        await self.ready()
        self.bridge.devices['new']['endpoints'] = {'11': {}}
        with self.assertRaises(ValueError):
            await self.flow.apply(True)
        self.assertEqual(self.bridge.calls, [])

    async def test_missing_group_stops_before_deletion(self):
        await self.ready()
        self.bridge.groups.clear()
        with self.assertRaises(ValueError):
            await self.flow.apply(True)
        self.assertEqual(self.bridge.calls, [])

    async def test_success_ack_without_membership_does_not_advance(self):
        await self.ready()
        original = self.bridge.request
        async def no_membership(operation, payload):
            if operation == 'group/members/add':
                return {}
            return await original(operation, payload)
        self.bridge.request = no_membership
        with self.assertRaises(ValueError):
            await self.flow.apply(True)
        self.assertEqual(self.flow.snapshot()['stage'], 'attention')

    async def test_changed_old_name_requires_new_review_before_removal(self):
        await self.ready()
        self.bridge.devices['old']['friendly_name'] = 'Renamed elsewhere'
        with self.assertRaises(ValueError):
            await self.flow.apply(True)
        self.assertEqual(self.bridge.calls, [])

    async def test_no_overlapping_apply(self):
        await self.ready()
        gate = asyncio.Event()
        original = self.bridge.request
        async def delayed(operation, payload):
            await gate.wait()
            return await original(operation, payload)
        self.bridge.request = delayed
        task = asyncio.create_task(self.flow.apply(True))
        await asyncio.sleep(0)
        with self.assertRaises(ValueError):
            await self.flow.apply(True)
        gate.set()
        await task

    async def test_group_changed_since_review_stops_before_removal(self):
        await self.ready()
        self.bridge.groups[0]['members'].clear()
        with self.assertRaises(ValueError):
            await self.flow.apply(True)
        self.assertEqual(self.bridge.calls, [])

    async def test_failed_review_save_leaves_saved_selection_unchanged(self):
        await self.flow.begin('old')
        before = self.flow.snapshot()
        async def fail_save(session):
            raise OSError('disk full')
        self.flow.save = fail_save
        with self.assertRaises(OSError):
            await self.flow.select('new')
        self.assertEqual(self.flow.snapshot(), before)
        self.assertEqual(self.bridge.calls, [])

    async def test_failed_completion_save_does_not_claim_complete(self):
        await self.ready()
        await self.flow.apply(True)
        before = self.flow.snapshot()
        async def fail_save(session):
            raise OSError('disk full')
        self.flow.save = fail_save
        with self.assertRaises(OSError):
            await self.flow.finish(True)
        self.assertEqual(self.flow.snapshot(), before)
        self.assertEqual(self.flow.snapshot()['stage'], 'verify')

    async def test_failed_initial_save_does_not_leave_an_active_swap(self):
        async def fail_save(session):
            raise OSError('disk full')
        self.flow.save = fail_save
        with self.assertRaises(OSError):
            await self.flow.begin('old')
        self.assertIsNone(self.flow.snapshot())
        self.assertEqual(self.bridge.calls, [])

    async def test_disabled_omissions_are_saved_without_discarding_original_snapshot(self):
        omitted=[{'entity_id':'sensor.legacy','reason':'Disabled and unavailable on replacement'}]
        self.bridge.validate_entities=lambda session:omitted
        await self.ready()
        self.assertEqual(self.flow.snapshot()['skipped_entities'],omitted)
        self.assertEqual(self.bridge.calls,[])

    async def test_omitted_legacy_registry_cleanup_does_not_invalidate_review(self):
        original=self.bridge.entities
        legacy={'entity_id':'sensor.legacy','unique_id':'old_legacy_zigbee2mqtt','domain':'sensor','disabled_by':'integration'}
        old_entities=original('old')+[legacy]
        self.bridge.entities=lambda ieee:old_entities if ieee=='old' else original(ieee)
        self.bridge.validate_entities=lambda session:[{'entity_id':'sensor.legacy','reason':'Disabled and unavailable on replacement'}]
        await self.ready()
        old_entities.pop()
        await self.flow.apply(True)
        self.assertEqual(self.flow.snapshot()['stage'],'verify')
