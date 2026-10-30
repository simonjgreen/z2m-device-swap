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
    click('flash-old')
    assert evaluate('serviceCalls') == [{'domain':'button','service':'press','data':{'entity_id':'button.old_identify'}}], 'Identify must use the selected bulb native button'
    assert evaluate("calls.filter(c=>c.action==='flash').length") == 0, 'Identify must not use generic HA flash'
    assert 'Identification requested for Kitchen 1' in evaluate('card.shadowRoot.textContent')
    click('begin')
    assert evaluate("card.shadowRoot.querySelector('#replacement').value") == ''
    choose('#replacement','new');click('select')
    assert evaluate("card.shadowRoot.querySelector('[data-action=apply]').disabled")
    assert 'light.kitchen_1_2' in evaluate('card.shadowRoot.textContent')
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
print('Card browser checks passed: explicit selection, reviewed IDs, confirmation gates, physical check, mobile layout.')
