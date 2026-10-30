"""Exercise the real web component in Chromium against the local preview only."""
import base64
import json
import time
from pathlib import Path
import urllib.request
from websockets.sync.client import connect

pages = json.load(urllib.request.urlopen('http://127.0.0.1:9223/json'))
page = next(p for p in pages if p['type']=='page')
with connect(page['webSocketDebuggerUrl'], max_size=16*1024*1024) as ws:
    seq=0
    def call(method, params=None):
        global seq
        seq+=1
        ws.send(json.dumps({'id':seq,'method':method,'params':params or {}}))
        while True:
            msg=json.loads(ws.recv(timeout=15))
            if msg.get('id')==seq:
                if 'error' in msg: raise RuntimeError(msg['error'])
                return msg.get('result',{})
    def evaluate(expression):
        result=call('Runtime.evaluate',{'expression':expression,'awaitPromise':True,'returnByValue':True})
        if 'exceptionDetails' in result: raise RuntimeError(result['exceptionDetails'])
        return result.get('result',{}).get('value')
    def navigate(url):
        target=url+('&' if '?' in url else '?')+'run='+str(time.time_ns())
        call('Page.navigate',{'url':target})
        deadline=time.monotonic()+15
        while time.monotonic()<deadline:
            try:
                if evaluate('location.href === '+json.dumps(target)+" && document.readyState === 'complete' && !!window.card?.shadowRoot.querySelector('#old')"):
                    return
            except RuntimeError:
                pass
            time.sleep(.05)
        raise RuntimeError('Preview did not finish loading')
    def settle():
        evaluate('new Promise(resolve=>setTimeout(resolve,200))')
    def click(action):
        evaluate(f"card.shadowRoot.querySelector('[data-action=\"{action}\"]').click()")
        settle()
    def choose(selector,value):
        evaluate(f"(()=>{{const select=card.shadowRoot.querySelector('{selector}');select.value='{value}';select.dispatchEvent(new Event('change'));}})()")
        settle()
    def screenshot(name):
        data=call('Page.captureScreenshot',{'format':'png'})['data']
        Path('/tmp/'+name).write_bytes(base64.b64decode(data))
    call('Page.enable')
    call('Network.enable')
    call('Network.setCacheDisabled',{'cacheDisabled':True})
    call('Emulation.setDeviceMetricsOverride',{'width':900,'height':1000,'deviceScaleFactor':1,'mobile':False})
    navigate('http://127.0.0.1:8765/tests/card-preview.html')
    evaluate("new Promise(resolve=>{const wait=()=>window.card?.shadowRoot.querySelector('#old')?resolve(true):setTimeout(wait,50);wait()})")
    assert evaluate("card.shadowRoot.querySelector('[data-action=begin]').disabled")
    evaluate("window.originalSearch=card.shadowRoot.querySelector('#search');originalSearch.focus()")
    for char in 'Kitchen':
        call('Input.insertText',{'text':char})
        assert evaluate("card.shadowRoot.querySelector('#search') === originalSearch"), 'Typing replaced the search input'
        assert evaluate('card.shadowRoot.activeElement === originalSearch'), 'Typing lost search focus'
    assert evaluate('originalSearch.value') == 'Kitchen'
    evaluate("previewData.devices[0].state='on';card._last='';card.refresh()")
    settle()
    assert evaluate("card.shadowRoot.querySelector('#search') === originalSearch"), 'Inventory refresh replaced the focused search input'
    assert evaluate('card.shadowRoot.activeElement === originalSearch'), 'Inventory refresh lost search focus'
    assert evaluate("card.shadowRoot.querySelectorAll('#old option').length") == 2
    choose('#old','old')
    assert 'Philips' in evaluate("card.shadowRoot.querySelector('#old-details').textContent"), 'Selected bulb must show make'
    assert '929001953101' in evaluate("card.shadowRoot.querySelector('#old-details').textContent"), 'Selected bulb must show model'
    click('flash-old')
    assert evaluate('serviceCalls') == [{'domain':'button','service':'press','data':{'entity_id':'button.old_identify'}}], 'Identify must use the selected bulb native button'
    assert evaluate("calls.filter(c=>c.action==='flash').length") == 0, 'Identify must not use generic HA flash'
    assert 'Identification requested for Kitchen 1' in evaluate('card.shadowRoot.textContent')
    click('begin')
    assert evaluate("card.shadowRoot.querySelector('#replacement').value") == ''
    choose('#replacement','new');click('select')
    assert evaluate("card.shadowRoot.querySelector('[data-action=apply]').disabled")
    assert 'light.kitchen_1_2' in evaluate('card.shadowRoot.textContent')
    assert 'sensor.legacy' not in evaluate("card.shadowRoot.querySelector('.entities').textContent")
    assert 'sensor.legacy' in evaluate('card.shadowRoot.textContent')
    assert 'will not be carried over' in evaluate('card.shadowRoot.textContent')
    screenshot('z2m-swap-review.png')
    evaluate("card.shadowRoot.querySelector('#confirm').click()")
    assert not evaluate("card.shadowRoot.querySelector('[data-action=apply]').disabled")
    click('apply')
    assert evaluate("card.shadowRoot.querySelector('[data-action=finish]').disabled")
    evaluate("card.shadowRoot.querySelector('#confirm').click()")
    click('finish')
    assert 'Replacement checked and complete' in evaluate('card.shadowRoot.textContent')
    assert evaluate("calls.filter(c=>c.action==='apply').every(c=>c.confirmed===true)")
    call('Emulation.setDeviceMetricsOverride',{'width':390,'height':844,'deviceScaleFactor':1,'mobile':True})
    navigate('http://127.0.0.1:8765/tests/card-preview.html?theme=dark')
    evaluate("new Promise(resolve=>{const wait=()=>window.card?.shadowRoot.querySelector('#old')?resolve(true):setTimeout(wait,50);wait()})")
    evaluate("new Promise(resolve=>{const wait=()=>new URLSearchParams(location.search).get('theme')==='dark' && document.body.classList.contains('dark') && window.card?.shadowRoot.querySelector('#old')?resolve(true):setTimeout(wait,50);wait()})")
    choose('#old','old');click('begin');choose('#replacement','new');click('select')
    assert evaluate('document.documentElement.scrollWidth <= window.innerWidth')
    screenshot('z2m-swap-mobile-dark.png')
    # New MQTT inventory should suggest a replacement without performing Review or Apply.
    call('Emulation.setDeviceMetricsOverride',{'width':900,'height':1000,'deviceScaleFactor':1,'mobile':False})
    navigate('http://127.0.0.1:8765/tests/card-preview.html')
    choose('#old','old');click('begin')
    evaluate("previewData.devices.push({...previewData.devices[1],ieee_address:'joined',friendly_name:'New arrival'});card.refresh()")
    settle()
    assert evaluate("card.shadowRoot.querySelector('#replacement').value") == 'joined', 'A single new bulb must be preselected'
    assert 'likely' in evaluate('card.shadowRoot.textContent').lower()
    assert 'identify' in evaluate("card.shadowRoot.querySelector('#detected').textContent").lower()
    assert not evaluate("calls.some(c=>['select','apply'].includes(c.action))"), 'Detection must not advance review or apply'
    evaluate("card._pairingSession=null;card._selectedNew='';card._last='';card.refresh()")
    settle()
    assert evaluate("card.shadowRoot.querySelector('#replacement').value") == 'joined', 'Saved pairing baseline must survive a card reload'
    choose('#replacement','new')
    evaluate("previewData.devices.push({...previewData.devices[1],ieee_address:'later',friendly_name:'Another arrival'});card.refresh()")
    settle()
    assert evaluate("card.shadowRoot.querySelector('#replacement').value") == 'new', 'New arrivals must not override a manual choice'
    assert evaluate("card.shadowRoot.querySelector('#detected')") is None
    navigate('http://127.0.0.1:8765/tests/card-preview.html')
    choose('#old','old');click('begin')
    evaluate("previewData.devices.push(...['a','b'].map(id=>({...previewData.devices[1],ieee_address:id,friendly_name:id})));card.refresh()")
    settle()
    assert evaluate("card.shadowRoot.querySelector('#replacement').value") == '', 'Simultaneous arrivals need an explicit choice'
    assert 'multiple' in evaluate('card.shadowRoot.textContent').lower()
    # Normal dashboard setup needs no entry ID or YAML lookup.
    navigate('http://127.0.0.1:8765/tests/card-preview.html')
    evaluate("calls.length=0;card.setConfig({type:'custom:z2m-device-swap-card'});card.hass=card._hass")
    settle()
    assert evaluate("!!card.shadowRoot.querySelector('#old')"), 'A sole integration must connect automatically'
    assert evaluate("calls.filter(c=>c.type==='z2m_device_swap/status').at(-1).entry_id") == 'preview'
    evaluate("card.shadowRoot.querySelector('#search').focus();previewEntries.push({entry_id:'second',domain:'z2m_device_swap',title:'Device Swap (second broker)'});calls.length=0;card.setConfig({type:'custom:z2m-device-swap-card'})")
    settle()
    assert not evaluate("calls.some(c=>c.type==='z2m_device_swap/status')"), 'Multiple integrations must not be selected arbitrarily'
    assert 'editor' in evaluate('card.shadowRoot.textContent').lower()
    assert not evaluate("!!card.shadowRoot.querySelector('#old')"), 'Reconfiguration must clear the previous bulb controls'
    evaluate("window.editor=card.constructor.getConfigElement();document.body.append(editor);editor.setConfig({type:'custom:z2m-device-swap-card',extra:'keep'});editor.hass=card._hass;window.editorConfigs=[];editor.addEventListener('config-changed',event=>editorConfigs.push(event.detail.config))")
    settle()
    assert 'second broker' in evaluate('editor.shadowRoot.textContent')
    evaluate("(()=>{const select=editor.shadowRoot.querySelector('select');select.value='second';select.dispatchEvent(new Event('change'));})()")
    assert evaluate('editorConfigs.at(-1)') == {'type':'custom:z2m-device-swap-card','extra':'keep','entry_id':'second'}
    evaluate('card.setConfig(editorConfigs.at(-1))')
    settle()
    assert evaluate("calls.filter(c=>c.type==='z2m_device_swap/status').at(-1).entry_id") == 'second'
    evaluate("(()=>{const select=editor.shadowRoot.querySelector('select');select.value='';select.dispatchEvent(new Event('change'));})()")
    assert 'entry_id' not in evaluate('editorConfigs.at(-1)')
    evaluate("previewEntries=[];calls.length=0;card.setConfig({type:'custom:z2m-device-swap-card'})")
    settle()
    assert not evaluate("calls.some(c=>c.type==='z2m_device_swap/status')")
    assert 'add integration' in evaluate('card.shadowRoot.textContent').lower()
    # A late response from the previous entry must not refill a reconfigured card.
    navigate('http://127.0.0.1:8765/tests/card-preview.html')
    evaluate("window.originalWS=card._hass.callWS.bind(card._hass);card._hass.callWS=msg=>msg.type==='z2m_device_swap/status' && msg.entry_id==='delayed'?new Promise(resolve=>window.resolveDelayed=()=>resolve({...previewData,marker:'stale'})):originalWS(msg);card.setConfig({entry_id:'delayed'})")
    settle()
    evaluate("card.setConfig({entry_id:'second'});resolveDelayed()")
    settle()
    assert evaluate('card.entryId') == 'second'
    assert evaluate("card._data.marker || null") is None, 'Late status must not restore the old entry data'
    assert 'entry_id' not in evaluate('card.constructor.getStubConfig()')
print('Card browser checks passed: automatic setup, visual entry picker, multiple/missing integrations, make/model, detection, manual choice, confirmation gates, mobile layout.')
