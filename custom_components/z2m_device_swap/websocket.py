"""Admin-only UI commands. No arbitrary MQTT publishing surface."""
import probatio as vol
from homeassistant.components import websocket_api
from homeassistant.core import callback
from .const import DOMAIN
from .mapping import identify_service
from .workflow import light_features


def status(runtime):
    bridge = runtime['bridge']
    inventory = bridge.status()
    bulbs = []
    for device in inventory.pop('devices'):
        try:
            light_features(device)
        except (ValueError, AttributeError):
            continue
        entities = bridge.entities(device['ieee_address'])
        states = [bridge.hass.states.get(e['entity_id']) for e in entities if e['domain'] == 'light']
        bulbs.append({'ieee_address': device['ieee_address'], 'friendly_name': device['friendly_name'],
                      'manufacturer': (device.get('definition') or {}).get('vendor') or device.get('manufacturer'),
                      'model': (device.get('definition') or {}).get('model') or device.get('model_id'),
                      'description': (device.get('definition') or {}).get('description'),
                      'interview_completed': device.get('interview_completed'),
                      'entities': entities, 'state': next((s.state for s in states if s), 'unknown')})
    return {**inventory, 'devices': bulbs, 'session': runtime['workflow'].snapshot(),
            'busy': runtime['workflow'].lock.locked() or runtime['action_lock'].locked()}


@websocket_api.websocket_command({vol.Required('type'): DOMAIN + '/status', vol.Required('entry_id'): str})
@websocket_api.require_admin
@websocket_api.async_response
async def ws_status(hass, connection, msg):
    runtime = hass.data[DOMAIN]['entries'].get(msg['entry_id'])
    if runtime is None:
        connection.send_error(msg['id'], 'not_loaded', 'Device Swap is not loaded')
        return
    connection.send_result(msg['id'], status(runtime))


@websocket_api.websocket_command({
    vol.Required('type'): DOMAIN + '/action', vol.Required('entry_id'): str,
    vol.Required('action'): vol.In(['begin', 'select', 'pair', 'apply', 'finish', 'cancel', 'flash']),
    vol.Optional('device'): str, vol.Optional('session_id'): str,
    vol.Optional('confirmed', default=False): bool,
})
@websocket_api.require_admin
@websocket_api.async_response
async def ws_action(hass, connection, msg):
    runtime = hass.data[DOMAIN]['entries'].get(msg['entry_id'])
    if runtime is None:
        connection.send_error(msg['id'], 'not_loaded', 'Device Swap is not loaded')
        return
    flow, bridge, lock = runtime['workflow'], runtime['bridge'], runtime['action_lock']
    if lock.locked():
        connection.send_error(msg['id'], 'busy', 'Another swap action is running')
        return
    try:
        async with lock:
            await bridge.ready()
            action = msg['action']
            session = flow.snapshot()
            if action not in ('begin', 'flash') and (not session or msg.get('session_id') != session['id']):
                raise ValueError('This screen is out of date. Refresh before continuing.')
            if action == 'flash':
                entities = bridge.entities(msg.get('device', ''))
                light = next((e for e in entities if e['domain'] == 'light'), None)
                if not light or msg.get('device') not in bridge.devices:
                    raise ValueError('Select a known Zigbee2MQTT bulb')
                effects = {e['entity_id']: state.attributes.get('effect_list', [])
                           for e in entities if e['domain'] == 'light'
                           and (state := hass.states.get(e['entity_id'])) is not None}
                domain, service, payload = identify_service(entities, effects)
                await hass.services.async_call(domain, service, payload, blocking=True)
            elif action == 'pair':
                if session['stage'] != 'select':
                    raise ValueError('Pairing is only available before selecting a replacement')
                await bridge.pair()
            elif action in ('begin', 'select'):
                if not msg.get('device'):
                    raise ValueError('Select a bulb first')
                await getattr(flow, action)(msg['device'])
            elif action in ('apply', 'finish'):
                await getattr(flow, action)(msg['confirmed'])
            else:
                await flow.cancel()
        connection.send_result(msg['id'], status(runtime))
    except (ValueError, KeyError, TimeoutError, ConnectionError) as error:
        connection.send_error(msg['id'], 'swap_failed', str(error))


@callback
def register(hass):
    websocket_api.async_register_command(hass, ws_status)
    websocket_api.async_register_command(hass, ws_action)
