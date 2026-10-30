"""Read-only authenticated API queries; token remains in process memory."""
import argparse
import getpass
import json
import sys
from websockets.sync.client import connect

parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--ha-url', required=True)
parser.add_argument('command')
args=parser.parse_args()
token = getpass.getpass('HA token: ')
with connect(args.ha_url.rstrip('/').replace('http:', 'ws:').replace('https:', 'wss:')+'/api/websocket', max_size=32*1024*1024) as ws:
    ws.recv()
    ws.send(json.dumps({'type':'auth','access_token':token}))
    if json.loads(ws.recv())['type'] != 'auth_ok':
        raise RuntimeError('Authentication failed')
    token = None
    command = json.loads(args.command)
    command['id'] = 1
    if command.get('type') == 'supervisor/api' and command.get('method') != 'get':
        raise ValueError('This helper permits read-only Supervisor queries')
    if command.get('type') not in ('supervisor/api', 'config/entity_registry/list', 'config/device_registry/list'):
        raise ValueError('Unsupported read-only query')
    ws.send(json.dumps(command))
    result=json.loads(ws.recv())
    if command.get('endpoint') == '/addons' and result.get('success'):
        data = result['result']
        print(json.dumps({'success':True,'addons': [{k:a.get(k) for k in ('slug','name','state','version')} for a in data.get('addons',[])]}))
    else:
        print(json.dumps(result))
