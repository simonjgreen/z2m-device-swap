"""Read-only HA inventory. Token is prompted without echo and never saved."""
import argparse
import getpass
import json
import urllib.request
from websockets.sync.client import connect


ROOMS = ('master bedroom', 'kitchen', 'utility', 'toilet')

def relevant(value):
    return any(room in value.lower().replace('_', ' ') for room in ROOMS)

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ha-url', required=True)
    args=parser.parse_args()
    base=args.ha_url.rstrip('/')
    token = getpass.getpass('HA token: ')
    headers = {'Authorization': 'Bearer ' + token}
    def get(path):
        return json.load(urllib.request.urlopen(urllib.request.Request(base + path, headers=headers), timeout=15))
    config = get('/api/config')
    print(json.dumps({'ha_version': config['version']}))
    states = {s['entity_id']: s for s in get('/api/states')}
    print(json.dumps({'lights': [{'entity_id': s['entity_id'], 'name': s['attributes'].get('friendly_name'),
                                  'state': s['state'], 'last_reported': s.get('last_reported')}
                                 for s in states.values() if s['entity_id'].startswith('light.') and
                                 relevant(s['entity_id'] + ' ' + s['attributes'].get('friendly_name', ''))]}))
    with connect(base.replace('http:', 'ws:').replace('https:', 'wss:') + '/api/websocket', open_timeout=15, max_size=32 * 1024 * 1024) as ws:
        ws.recv()
        ws.send(json.dumps({'type': 'auth', 'access_token': token}))
        if json.loads(ws.recv())['type'] != 'auth_ok':
            raise RuntimeError('Authentication failed')
        seq = 0
        def query(kind, **kwargs):
            nonlocal seq
            seq += 1
            ws.send(json.dumps({'id': seq, 'type': kind, **kwargs}))
            result = json.loads(ws.recv())
            if not result.get('success'):
                raise RuntimeError(str(result.get('error')))
            return result['result']
        entities = query('config/entity_registry/list')
        devices = {d['id']: d for d in query('config/device_registry/list')}
        print(json.dumps({'mqtt_lights': [{'entity_id': e['entity_id'], 'unique_id': e['unique_id'],
                                           'device': {k: devices.get(e.get('device_id'), {}).get(k)
                                                      for k in ('name', 'model', 'manufacturer', 'identifiers')}}
                                          for e in entities if e['platform'] == 'mqtt' and
                                          e['entity_id'].startswith('light.') and relevant(e['entity_id'])]}))
        entries = query('config_entries/get')
        print(json.dumps({'mqtt_entries': [{k: e.get(k) for k in ('entry_id', 'domain', 'title', 'state')}
                                          for e in entries if e['domain'] in ('mqtt', 'hassio')]}))
        addons = query('supervisor/api', endpoint='/addons', method='get')
        print(json.dumps({'addons': [{k:a.get(k) for k in ('slug','name','version','state')} for a in addons.get('addons', []) if any(w in a.get('name','').lower() for w in ('zigbee','ssh','studio','file','samba'))]}))
        seq += 1
        ws.send(json.dumps({'id': seq, 'type': 'mqtt/subscribe', 'topic': 'zigbee2mqtt/bridge/#', 'qos': 0}))
        seen = set()
        while len(seen) < 3:
            try:
                message = json.loads(ws.recv(timeout=8))
            except TimeoutError:
                break
            if message.get('type') != 'event':
                if message.get('success') is False:
                    print(json.dumps({'mqtt_error': message.get('error')}))
                    break
                continue
            event = message['event']
            topic = event.get('topic', '')
            try:
                payload = json.loads(event.get('payload', ''))
            except (ValueError, TypeError):
                continue
            key = topic.rsplit('/', 1)[-1]
            if key == 'devices':
                seen.add(key)
                print(json.dumps({'z2m_devices': [{'ieee_address': d['ieee_address'], 'friendly_name': d['friendly_name'], 'model': (d.get('definition') or {}).get('model'), 'vendor': (d.get('definition') or {}).get('vendor'), 'endpoints': list(d.get('endpoints', {})), 'interview_completed': d.get('interview_completed')} for d in payload if relevant(d.get('friendly_name', ''))]}))
            elif key == 'groups':
                seen.add(key)
                print(json.dumps({'z2m_groups': [g for g in payload if relevant(g.get('friendly_name', ''))]}))
            elif key == 'info':
                seen.add(key)
                print(json.dumps({'z2m_info': {k: payload.get(k) for k in ('version', 'permit_join', 'restart_required')}}))
    try:
        addons = get('/api/hassio/addons')
        print(json.dumps({'addons': [{k:a.get(k) for k in ('slug','name','version','state')}
                                    for a in addons.get('data',{}).get('addons',[])
                                    if any(w in a.get('name','').lower() for w in ('zigbee','ssh','studio','file','samba'))]}))
    except Exception as error:
        print(json.dumps({'addon_inspection': type(error).__name__}))

if __name__ == '__main__':
    main()
