"""Replace faulty Zigbee2MQTT bulbs from Home Assistant."""
import asyncio
from pathlib import Path
from homeassistant.components import frontend, panel_custom
from homeassistant.components.http import StaticPathConfig
from homeassistant.helpers.storage import Store
from .bridge import Bridge
from .const import BASE_TOPIC, DOMAIN
from .workflow import Workflow
from .websocket import register


async def async_setup(hass, config):
    hass.data.setdefault(DOMAIN, {'entries': {}})
    await hass.http.async_register_static_paths([
        StaticPathConfig('/z2m_device_swap', str(Path(__file__).parent / 'frontend'), False)])
    register(hass)
    return True


async def async_setup_entry(hass, entry):
    bridge = Bridge(hass, entry.data[BASE_TOPIC])
    store = Store(hass, 1, f'{DOMAIN}.{entry.entry_id}')
    journal = await store.async_load() or {'current': None, 'history': []}
    stored = journal['current']
    async def save(session):
        previous = journal['current']
        history = list(journal['history'])
        if previous and previous['id'] != session['id']:
            history = (history + [previous])[-20:]
        updated = {'current': session, 'history': history}
        await store.async_save(updated)
        journal.update(updated)
    flow = Workflow(bridge, save, stored)
    if stored and stored['stage'] == 'applying':
        await flow._persist(stage='attention', error='Home Assistant restarted during replacement. Review before resuming.')
    await bridge.start()
    path = 'z2m-device-swap-' + entry.entry_id
    runtime = {'bridge': bridge, 'workflow': flow, 'store': store,
               'action_lock': asyncio.Lock(), 'panel_path': path}
    hass.data[DOMAIN]['entries'][entry.entry_id] = runtime
    try:
        await panel_custom.async_register_panel(hass, frontend_url_path=path,
            webcomponent_name='z2m-device-swap-panel', sidebar_title='Replace a bulb',
            sidebar_icon='mdi:lightbulb-auto', module_url='/z2m_device_swap/z2m-device-swap-card.js?v=0.1.0',
            config={'entry_id': entry.entry_id}, require_admin=True)
    except Exception:
        bridge.stop()
        hass.data[DOMAIN]['entries'].pop(entry.entry_id, None)
        raise
    return True


async def async_unload_entry(hass, entry):
    runtime = hass.data[DOMAIN]['entries'].get(entry.entry_id)
    if runtime and (runtime['workflow'].lock.locked() or runtime['action_lock'].locked()):
        return False
    if runtime:
        runtime['bridge'].stop()
        frontend.async_remove_panel(hass, runtime['panel_path'])
        hass.data[DOMAIN]['entries'].pop(entry.entry_id, None)
    return True
