"""Inspect or install this integration through the user's File editor add-on.

Never restarts HA or changes Zigbee devices. Prompts for a token without echo.
Default is a read-only file plan. --install writes only this component directory.
"""
import argparse
import getpass
import hashlib
import json
import re
import subprocess
from pathlib import Path, PurePosixPath
import urllib.parse
import urllib.request
from websockets.sync.client import connect


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ha-url', required=True)
    parser.add_argument('--install', action='store_true')
    parser.add_argument('--update-from', help='Expected installed Git commit; changed files are backed up before update')
    args=parser.parse_args()
    base=args.ha_url.rstrip('/')
    token=getpass.getpass('HA token: ')
    with connect(base.replace('http:', 'ws:').replace('https:', 'wss:')+'/api/websocket', max_size=16*1024*1024) as ws:
        ws.recv(); ws.send(json.dumps({'type':'auth','access_token':token}))
        if json.loads(ws.recv())['type']!='auth_ok': raise RuntimeError('Authentication failed')
        def query(seq,endpoint,method='get',data=None):
            command={'id':seq,'type':'supervisor/api','endpoint':endpoint,'method':method}
            if data is not None: command['data']=data
            ws.send(json.dumps(command)); result=json.loads(ws.recv())
            if not result.get('success'): raise RuntimeError('Supervisor request failed')
            return result['result']
        info=query(1,'/addons/core_configurator/info')
        session=query(2,'/ingress/session','post',{})['session']
    ingress=info.get('ingress_url')
    if not ingress or not ingress.startswith('/api/hassio_ingress/'):
        raise RuntimeError('File editor ingress is not available')
    headers={'Authorization':'Bearer '+token, 'Cookie':'ingress_session='+session}
    def request(path, values=None, raw=False):
        data=urllib.parse.urlencode(values).encode() if values is not None else None
        request_headers=dict(headers)
        if data is not None: request_headers['Content-Type']='application/x-www-form-urlencoded'
        req=urllib.request.Request(base+ingress+path,data=data,headers=request_headers)
        try:
            value=urllib.request.urlopen(req,timeout=20).read()
        except urllib.error.HTTPError as error:
            raise RuntimeError(f'File editor returned HTTP {error.code}') from None
        if raw: return value
        result=json.loads(value)
        if result.get('error'): raise RuntimeError('File editor operation failed: '+str(result.get('message',result['error'])))
        return result
    root=request('/api/abspath?path=.',raw=True).decode().strip()
    if root not in ('/config','/homeassistant'):
        raise RuntimeError('Unexpected File editor root; inspect manually before installing')
    component=root+'/custom_components/z2m_device_swap'
    files=sorted(p for p in (Path(__file__).parents[1]/'custom_components/z2m_device_swap').rglob('*')
                 if p.is_file() and p.suffix in ('.py','.json','.js'))
    print(json.dumps({'config_root':root,'target':component,'files':len(files),'mode':'install' if args.install else 'plan'}))
    # Only examine our own component; no configuration or secret files are read.
    existing=request('/api/file?'+urllib.parse.urlencode({'filename':component+'/manifest.json'}),raw=True)
    if args.update_from:
        if existing == b'File not found':
            raise RuntimeError('No existing installation to update')
        if not re.fullmatch(r'[0-9a-f]{7,40}', args.update_from):
            raise ValueError('Expected a hexadecimal Git commit')
        repo=Path(__file__).parents[1]
        commit=subprocess.check_output(['git','rev-parse','--verify',args.update_from+'^{commit}'],cwd=repo,text=True).strip()
        changes=[]
        for file in files:
            relative=file.relative_to(repo/'custom_components/z2m_device_swap')
            target=str(PurePosixPath(component)/relative.as_posix())
            old=subprocess.check_output(['git','show',commit+':custom_components/z2m_device_swap/'+relative.as_posix()],cwd=repo)
            remote=request('/api/file?'+urllib.parse.urlencode({'filename':target}),raw=True)
            if remote != old:
                raise RuntimeError('Remote differs from expected commit: '+str(relative))
            if file.read_bytes() != old:
                changes.append((file,target,old))
        print('Verified installed baseline; changed files: '+str(len(changes)))
        if not args.install:
            print('Update plan only. No files changed.')
            return
        for file,target,old in changes:
            backup=target+'.before-'+commit[:12]
            saved=request('/api/file?'+urllib.parse.urlencode({'filename':backup}),raw=True)
            if saved not in (b'File not found', old):
                raise RuntimeError('Existing backup differs; refusing to overwrite it')
            request('/api/save',{'filename':backup,'text':old.decode()})
            if request('/api/file?'+urllib.parse.urlencode({'filename':backup}),raw=True) != old:
                raise RuntimeError('Backup verification failed')
            data=file.read_bytes()
            request('/api/save',{'filename':target,'text':data.decode()})
            if request('/api/file?'+urllib.parse.urlencode({'filename':target}),raw=True) != data:
                raise RuntimeError('Updated file verification failed')
            print('Backed up and verified '+file.name)
        print('Update verified. HA was NOT restarted; no Zigbee changes made.')
        return
    if existing != b'File not found':
        raise RuntimeError('An existing Device Swap installation is present; use --update-from with its exact installed commit')
    if not args.install:
        print('Ready to create the new component directory. No files changed; HA was not restarted.')
        return
    request('/api/newfolder',{'path':root+'/custom_components','name':'z2m_device_swap'})
    for directory in ('frontend','translations'):
        request('/api/newfolder',{'path':component,'name':directory})
    source=Path(__file__).parents[1]/'custom_components/z2m_device_swap'
    for file in files:
        relative=file.relative_to(source)
        target=str(PurePosixPath(component)/relative.as_posix())
        data=file.read_bytes()
        request('/api/save',{'filename':target,'text':data.decode()})
        received=request('/api/file?'+urllib.parse.urlencode({'filename':target}),raw=True)
        if hashlib.sha256(received).digest()!=hashlib.sha256(data).digest():
            raise RuntimeError('Remote verification failed for '+str(relative))
        print('Verified '+str(relative))
    print('Integration files installed and verified. HA has NOT been restarted. No Zigbee changes were made.')

if __name__=='__main__':
    main()
