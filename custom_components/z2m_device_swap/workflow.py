"""Journaled bulb replacement, independent of Home Assistant imports."""
from __future__ import annotations

import asyncio
from copy import deepcopy
from datetime import datetime, timezone
from uuid import uuid4


def light_features(device):
    """Return required light capabilities; reject ambiguous multi-channel devices."""
    exposes = device.get('definition', {}).get('exposes', [])
    lights = [item for item in exposes if item.get('type') == 'light']
    if len(lights) != 1 or lights[0].get('endpoint'):
        raise ValueError('Only single-channel bulbs are supported in this version')
    return {f['property'] for f in lights[0].get('features', []) if 'property' in f}


def check_replacement(old, new):
    if old['ieee_address'] == new['ieee_address']:
        raise ValueError('Choose a different bulb')
    if not new.get('interview_completed') or not new.get('supported'):
        raise ValueError('Replacement must be supported and finish its interview')
    if not light_features(old).issubset(light_features(new)):
        raise ValueError('Replacement is missing light capabilities')


class Workflow:
    """One swap at a time. Caller refreshes bridge inventory before recovery."""

    def __init__(self, adapter, save, session=None):
        self.adapter = adapter
        self.save = save
        self.session = deepcopy(session)
        self.lock = asyncio.Lock()

    def snapshot(self):
        return deepcopy(self.session)

    async def _persist(self, **changes):
        candidate = self.snapshot() or {}
        candidate.update(changes)
        candidate['updated_at'] = datetime.now(timezone.utc).isoformat()
        await self.save(deepcopy(candidate))
        self.session = candidate

    async def begin(self, old):
        if self.lock.locked():
            raise ValueError('A swap action is already running')
        async with self.lock:
            if self.session and self.session['stage'] not in ('complete', 'cancelled'):
                raise ValueError('Finish or cancel the existing swap first')
            device = deepcopy(self.adapter.devices[old])
            light_features(device)
            entities = self.adapter.entities(old)
            if not entities or not any(e['domain'] == 'light' for e in entities):
                raise ValueError('No Home Assistant MQTT light found for this device')
            memberships = []
            for group in self.adapter.groups:
                for member in group.get('members', []):
                    if member['ieee_address'] == old:
                        memberships.append({'id': group['id'], 'name': group['friendly_name'],
                                            'endpoint': member['endpoint']})
            # Bulbs may have a second Green Power endpoint; only group endpoints matter here.
            endpoints = {m['endpoint'] for m in memberships}
            if len(endpoints) > 1:
                raise ValueError('Multiple group endpoints require manual replacement')
            session = {'version': 1, 'id': uuid4().hex, 'old': device,
                            'entities': deepcopy(entities), 'groups': memberships,
                            'replacement': None, 'known_devices': sorted(self.adapter.devices),
                            'skipped_entities': [], 'stage': 'select', 'pending': None,
                            'physical_test_confirmed': False, 'error': None}
            await self._persist(**session)

    async def select(self, new):
        if self.lock.locked():
            raise ValueError('A swap action is already running')
        async with self.lock:
            if not self.session or self.session['stage'] not in ('select', 'review'):
                raise ValueError('Start a swap before selecting a replacement')
            device = self.adapter.devices[new]
            check_replacement(self.session['old'], device)
            candidate = self.snapshot()
            candidate['replacement'] = deepcopy(device)
            skipped = self.adapter.validate_entities(candidate) or []
            await self._persist(replacement=deepcopy(device), skipped_entities=skipped, stage='review')

    async def _operation(self, pending, operation, payload):
        await self._persist(pending=pending)
        await self.adapter.request(operation, payload)
        await self._persist(pending=None)

    async def apply(self, confirmed):
        if confirmed is not True:
            raise ValueError('Explicit confirmation is required before removing a bulb')
        if self.lock.locked():
            raise ValueError('A swap action is already running')
        async with self.lock:
            if not self.session or self.session['stage'] not in ('review', 'attention', 'applying'):
                raise ValueError('Review a replacement first')
            old = self.session['old']
            new = self.session['replacement']
            if not new or new['ieee_address'] not in self.adapter.devices:
                raise ValueError('Replacement is missing from Zigbee2MQTT')
            check_replacement(old, self.adapter.devices[new['ieee_address']])
            self.adapter.validate_entities(self.snapshot())
            if self.session['stage'] == 'review' and self.adapter.devices.get(old['ieee_address'], {}).get('friendly_name') != old['friendly_name']:
                raise ValueError('The old bulb changed since review. Cancel and start a new snapshot.')
            if self.session['stage'] == 'review':
                current_memberships = {(g['id'], m['endpoint']) for g in self.adapter.groups for m in g.get('members', []) if m['ieee_address'] == old['ieee_address']}
                expected_memberships = {(g['id'], g['endpoint']) for g in self.session['groups']}
                omitted_ids = {e['entity_id'] for e in self.session.get('skipped_entities', [])}
                current_entities = {(e['entity_id'], e['unique_id']) for e in self.adapter.entities(old['ieee_address']) if e['entity_id'] not in omitted_ids}
                expected_entities = {(e['entity_id'], e['unique_id']) for e in self.session['entities'] if e['entity_id'] not in omitted_ids}
                if current_memberships != expected_memberships or current_entities != expected_entities:
                    raise ValueError('The old bulb changed since review. Cancel and start a new snapshot.')
            for membership in self.session['groups']:
                if not any(g['id'] == membership['id'] for g in self.adapter.groups):
                    raise ValueError('An original group no longer exists')
                if str(membership['endpoint']) not in self.adapter.devices[new['ieee_address']].get('endpoints', {}):
                    raise ValueError('Replacement has a different group endpoint')
            name = old['friendly_name']
            conflicts = [d for d in self.adapter.devices.values() if d['friendly_name'] == name
                         and d['ieee_address'] not in (old['ieee_address'], new['ieee_address'])]
            if conflicts:
                raise ValueError('Another device now owns the old name')
            await self._persist(stage='applying', error=None)
            try:
                if old['ieee_address'] in self.adapter.devices:
                    await self._operation('remove', 'device/remove', {'id': old['ieee_address'], 'force': True})
                if self.adapter.devices[new['ieee_address']]['friendly_name'] != name:
                    await self._operation('rename', 'device/rename', {
                        'from': new['ieee_address'], 'to': name, 'homeassistant_rename': True})
                for membership in self.session['groups']:
                    group = next((g for g in self.adapter.groups if g['id'] == membership['id']), None)
                    if not group:
                        raise ValueError(f"Group {membership['name']} no longer exists")
                    # Endpoint is explicit: reviewed single-channel bulbs use their group endpoint.
                    endpoint = membership['endpoint']
                    if str(endpoint) not in self.adapter.devices[new['ieee_address']].get('endpoints', {}):
                        raise ValueError('Replacement has a different group endpoint')
                    if not any(m['ieee_address'] == new['ieee_address'] and m['endpoint'] == endpoint
                               for m in group.get('members', [])):
                        await self._operation(f"group:{membership['id']}", 'group/members/add', {
                            'group': membership['id'], 'device': new['ieee_address'], 'endpoint': endpoint})
                if old['ieee_address'] in self.adapter.devices or self.adapter.devices[new['ieee_address']]['friendly_name'] != name:
                    raise ValueError('Bridge inventory does not confirm removal and rename')
                for membership in self.session['groups']:
                    if not any(g['id'] == membership['id'] and any(m['ieee_address'] == new['ieee_address'] and m['endpoint'] == membership['endpoint'] for m in g.get('members', [])) for g in self.adapter.groups):
                        raise ValueError('Bridge inventory does not confirm restored group membership')
                await self._persist(pending='entities')
                await self.adapter.restore_entities(self.snapshot())
                if not self.adapter.verify_entities(self.snapshot()):
                    raise ValueError('Home Assistant entity IDs have not been verified')
                await self._persist(stage='verify', pending=None)
            except BaseException as error:
                await self._persist(stage='attention', error=str(error) or type(error).__name__)
                raise

    async def finish(self, confirmed):
        if self.lock.locked():
            raise ValueError('A swap action is already running')
        async with self.lock:
            if not self.session or self.session['stage'] != 'verify' or confirmed is not True:
                raise ValueError('Confirm the physical light and automations work first')
            if not self.adapter.verify_entities(self.snapshot()):
                raise ValueError('Home Assistant entity IDs no longer match')
            await self._persist(stage='complete', physical_test_confirmed=True)

    async def cancel(self):
        if self.lock.locked():
            raise ValueError('A swap action is already running')
        async with self.lock:
            if not self.session or self.session['stage'] not in ('select', 'review'):
                raise ValueError('A started replacement must be recovered, not discarded')
            await self._persist(stage='cancelled')
