"""Configure Device Swap and verify its status without changing any bulbs."""
import argparse
import getpass
import json
from pathlib import Path
import time
import urllib.request
from websockets.sync.client import connect


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ha-url',required=True)
    parser.add_argument('--base-topic',default='zigbee2mqtt')
    parser.add_argument('--inspect-only',action='store_true')
    parser.add_argument('--dashboard',action='store_true',help='Create a native Lovelace dashboard containing the card')
    parser.add_argument('--status-output',type=Path)
    args=parser.parse_args()
    base=args.ha_url.rstrip('/')
    token=getpass.getpass('HA token: ')
    headers={'Authorization':'Bearer '+token,'Content-Type':'application/json'}
    def post(path,data):
        req=urllib.request.Request(base+path,data=json.dumps(data).encode(),headers=headers)
        try:
            return json.load(urllib.request.urlopen(req,timeout=30))
        except urllib.error.HTTPError as error:
            print(json.dumps({'http_error':error.code,'detail':error.read().decode()[:1000]}))
            raise RuntimeError('HA setup request failed') from None
    with connect(base.replace('http:','ws:').replace('https:','wss:')+'/api/websocket',max_size=16*1024*1024) as ws:
        ws.recv();ws.send(json.dumps({'type':'auth','access_token':token}))
        if json.loads(ws.recv())['type']!='auth_ok':raise RuntimeError('Authentication failed')
        seq=0
        def query(kind,**kwargs):
            nonlocal seq
            seq+=1
            ws.send(json.dumps({'id':seq,'type':kind,**kwargs}))
            while True:
                msg=json.loads(ws.recv(timeout=35))
                if msg.get('id')==seq:
                    if not msg.get('success'):raise RuntimeError(str(msg.get('error')))
                    return msg['result']
        entries=query('config_entries/get')
        matching=[e for e in entries if e['domain']=='z2m_device_swap']
        if matching:
            if len(matching)!=1:raise RuntimeError('Multiple Device Swap entries; select manually')
            entry=matching[0]
        else:
            if args.inspect_only:raise RuntimeError('Device Swap has not been configured')
            flow=post('/api/config/config_entries/flow',{'handler':'z2m_device_swap','show_advanced_options':False})
            print(json.dumps({'flow_type':flow.get('type'),'step_id':flow.get('step_id'),'errors':flow.get('errors'),'reason':flow.get('reason')}))
            if flow.get('type')!='form' or flow.get('step_id')!='user':
                raise RuntimeError('Unexpected configuration step')
            result=post('/api/config/config_entries/flow/'+flow['flow_id'],{'base_topic':args.base_topic})
            print(json.dumps({'result_type':result.get('type'),'errors':result.get('errors'),'reason':result.get('reason')}))
            if result.get('type')!='create_entry':raise RuntimeError('Configuration was not created')
            entry=result['result']
        entry_id=entry['entry_id']
        print(json.dumps({'entry_id':entry_id}))
        for attempt in range(15):
            entries=query('config_entries/get')
            entry=next(e for e in entries if e['entry_id']==entry_id)
            if entry.get('state') in ('setup_error','setup_retry'):
                print(json.dumps({k:entry.get(k) for k in ('entry_id','state','reason','error')}))
                raise RuntimeError('Integration did not load')
            if entry.get('state')=='loaded':break
            time.sleep(1)
        print(json.dumps({'entry_state':entry.get('state')}))
        status=None
        for attempt in range(15):
            status=query('z2m_device_swap/status',entry_id=entry_id)
            if status['online'] and status['inventory_ready']:break
            time.sleep(1)
        if args.status_output:
            args.status_output.write_text(json.dumps(status))
        print(json.dumps({'online':status['online'],'inventory_ready':status['inventory_ready'],
                          'z2m_version':status.get('version'),'bulbs':len(status['devices']),
                          'active_swap':status.get('session') is not None}))
        panel_path='z2m-device-swap'
        if args.dashboard:
            resources=query('lovelace/resources')
            resource_url='/z2m_device_swap/z2m-device-swap-card.js?v=0.1.5'
            if not any(r['url'].split('?')[0] == resource_url.split('?')[0] for r in resources):
                query('lovelace/resources/create',url=resource_url,res_type='module')
            dashboards=query('lovelace/dashboards/list')
            existing=next((d for d in dashboards if d['url_path']==panel_path),None)
            if existing is None:
                query('lovelace/dashboards/create',url_path=panel_path,title='Replace a bulb',icon='mdi:lightbulb-auto',show_in_sidebar=True,require_admin=True,mode='storage')
                config={'title':'Replace a bulb','views':[{'title':'Replace a bulb','path':'swap','type':'masonry',
                    'cards':[{'type':'custom:z2m-device-swap-card','entry_id':entry_id}]}]}
                query('lovelace/config/save',url_path=panel_path,config=config)
            config=query('lovelace/config',url_path=panel_path)
            print(json.dumps({'native_dashboard':True,'views':len(config.get('views',[])),'dashboard_url':base+'/'+panel_path}))
        panels=query('get_panels')
        panel=panels.get(panel_path,{})
        print(json.dumps({'panel_registered':bool(panel),'component_name':panel.get('component_name'),'panel_url':base+'/'+panel_path}))
        # Static frontend bytes are safe to read; no device action endpoint is called.
        js=urllib.request.urlopen(urllib.request.Request(base+'/z2m_device_swap/z2m-device-swap-card.js',headers=headers),timeout=15).read()
        print(json.dumps({'frontend_bytes':len(js),'frontend_contains_card':b'z2m-device-swap-card' in js}))

if __name__=='__main__':main()
