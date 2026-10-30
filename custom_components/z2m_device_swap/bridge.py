"""HA MQTT inventory and mutation adapter."""
import asyncio
from copy import deepcopy
import json
import time
from homeassistant.components import mqtt
from homeassistant.core import callback
from .registry import Registry
from .rpc import RPC


class Bridge(Registry):
    def __init__(self, hass, base_topic):
        super().__init__(hass, base_topic)
        self.devices = {}
        self.groups = []
        self.info = {}
        self.online = False
        self.received = set()
        self.unsubscribe = None
        self.rpc = RPC(self._publish, base_topic)
        self.last_failure = 0
        self.pairing_until = 0

    async def _publish(self, topic, payload):
        await mqtt.async_publish(self.hass, topic, json.dumps(payload), qos=1, retain=False)

    @callback
    def receive(self, message):
        try:
            payload = json.loads(message.payload)
        except (ValueError, TypeError):
            return
        suffix = message.topic[len(self.base_topic + '/bridge/'):]
        if suffix.startswith('response/'):
            if isinstance(payload, dict):
                self.rpc.receive(suffix[len('response/'):], payload)
        elif suffix == 'devices' and isinstance(payload, list):
            self.devices = {d['ieee_address']: d for d in payload if isinstance(d, dict) and 'ieee_address' in d}
            self.received.add('devices')
        elif suffix == 'groups' and isinstance(payload, list):
            self.groups = payload
            self.received.add('groups')
        elif suffix == 'info' and isinstance(payload, dict):
            self.info = {key: payload.get(key) for key in ('version', 'permit_join')}
            self.received.add('info')
        elif suffix == 'state':
            self.online = (payload.get('state') if isinstance(payload, dict) else payload) == 'online'
            self.received.add('state')

    async def start(self):
        self.unsubscribe = await mqtt.async_subscribe(self.hass, self.base_topic + '/bridge/#', self.receive, 1)

    def stop(self):
        if self.unsubscribe:
            self.unsubscribe()
        self.rpc.close()

    async def ready(self):
        if not mqtt.is_connected(self.hass) or not self.online:
            raise ValueError('MQTT or Zigbee2MQTT is offline')
        if not {'devices', 'groups', 'info', 'state'}.issubset(self.received):
            raise ValueError('Waiting for Zigbee2MQTT inventory')
        if time.monotonic() - self.last_failure < 35:
            raise ValueError('Wait 35 seconds after a bridge timeout before reviewing recovery')

    async def request(self, operation, payload):
        await self.ready()
        try:
            result = await self.rpc.request(operation, payload)
            # Bridge publishes inventory asynchronously; verify effects, not just acknowledgements.
            async with asyncio.timeout(15):
                while not self._effect_seen(operation, payload):
                    await asyncio.sleep(.1)
            return result
        except TimeoutError:
            self.last_failure = time.monotonic()
            raise TimeoutError('Bridge response or inventory update timed out. Review current state before resuming.') from None

    def _effect_seen(self, operation, payload):
        if operation == 'device/remove':
            return payload['id'] not in self.devices
        if operation == 'device/rename':
            return self.devices.get(payload['from'], {}).get('friendly_name') == payload['to']
        if operation == 'group/members/add':
            ieee, endpoint = payload['device'], str(payload['endpoint'])
            return any(g['id'] == payload['group'] and any(m['ieee_address'] == ieee and str(m['endpoint']) == endpoint
                       for m in g.get('members', [])) for g in self.groups)
        return True

    async def pair(self):
        await self.ready()
        if self.info.get('permit_join'):
            raise ValueError('Pairing is already open; use that window or wait for it to close')
        await self.request('permit_join', {'time': 120})
        self.pairing_until = time.time() + 120

    def status(self):
        return {'online': self.online and mqtt.is_connected(self.hass),
                'inventory_ready': {'devices', 'groups', 'info', 'state'}.issubset(self.received),
                'version': self.info.get('version'), 'permit_join': self.info.get('permit_join'),
                'pairing_until': self.pairing_until,
                'devices': deepcopy(list(self.devices.values())), 'groups': deepcopy(self.groups)}
