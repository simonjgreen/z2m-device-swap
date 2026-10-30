/* A dependency-free Home Assistant card and sidebar panel. */
const esc = (value) => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));

class DeviceSwapCard extends HTMLElement {
  constructor() {
    super(); this.attachShadow({mode:'open'}); this._config = {}; this._data = null;
    this._busy = false; this._error = ''; this._selectedOld = ''; this._selectedNew = '';
    this._confirm = false; this._query = ''; this._last = '';
  }
  setConfig(config) { this._config = config; this.refresh(); }
  set hass(hass) { this._hass = hass; if (!this._data && !this._loading) this.refresh(); }
  getCardSize() { return 7; }
  connectedCallback() { this._timer = setInterval(() => this.refresh(), 3000); this.render(); this.refresh(); }
  disconnectedCallback() { clearInterval(this._timer); }
  async refresh() {
    if (!this._hass || !this._config.entry_id || this._loading || this._busy) return;
    this._loading = true;
    try {
      const data = await this._hass.callWS({type:'z2m_device_swap/status', entry_id:this._config.entry_id});
      const serialized = JSON.stringify(data);
      if (serialized !== this._last) { this._data = data; this._last = serialized; this.render(); }
    } catch (error) { this._error = error.message || String(error); this.render(); }
    finally { this._loading = false; }
  }
  async action(action, extra = {}) {
    if (this._busy) return;
    this._busy = true; this._error = ''; this.render();
    try {
      this._data = await this._hass.callWS({type:'z2m_device_swap/action', entry_id:this._config.entry_id,
        action, session_id:this._data?.session?.id, ...extra});
      this._confirm = false;
    } catch (error) { this._error = error.message || String(error); }
    finally { this._busy = false; this._last = ''; this.render(); await this.refresh(); }
  }
  options(devices, selected) {
    return '<option value="">Choose a bulb…</option>' + devices.map(d =>
      `<option value="${esc(d.ieee_address)}" ${selected === d.ieee_address ? 'selected' : ''}>${esc(d.friendly_name)} · ${esc(d.state)}${d.interview_completed ? '' : ' · interviewing'}</option>`).join('');
  }
  selectedDetails(device) {
    if (!device) return '';
    return `<p class="muted">${esc(device.model)}<br><code>${esc(device.ieee_address)}</code></p>
      <ul>${device.entities.filter(e => e.domain === 'light').map(e => `<li><code>${esc(e.entity_id)}</code></li>`).join('')}</ul>`;
  }
  updateSearchResults() {
    const d = this._data;
    if (!d) return;
    const devices = [...d.devices].sort((a,b) => a.friendly_name.localeCompare(b.friendly_name, undefined, {numeric:true}));
    const filtered = devices.filter(item => (item.friendly_name + ' ' + item.entities.map(e=>e.entity_id).join(' ')).toLowerCase().includes(this._query.toLowerCase()));
    if (!filtered.some(item => item.ieee_address === this._selectedOld)) this._selectedOld = '';
    const selected = devices.find(item => item.ieee_address === this._selectedOld);
    this.shadowRoot.querySelector('#old').innerHTML = this.options(filtered, this._selectedOld);
    this.shadowRoot.querySelector('#old-details').innerHTML = this.selectedDetails(selected);
    const disabled = this._busy || d.busy || !d.online || !d.inventory_ready || !selected;
    for (const action of ['flash-old', 'begin']) this.shadowRoot.querySelector(`[data-action="${action}"]`).disabled = disabled;
    this.shadowRoot.querySelector('.badge').textContent = d.online ? 'Zigbee2MQTT connected' : 'Offline';
    const error = this.shadowRoot.querySelector('#error');
    error.textContent = this._error; error.hidden = !this._error;
  }
  render() {
    const d = this._data, s = d?.session;
    const stage = s?.stage || 'idle';
    if (this.shadowRoot.activeElement?.id === 'search' && this._renderStage === stage && ['idle','complete','cancelled'].includes(stage)) {
      this.updateSearchResults();
      return;
    }
    this._renderStage = stage;
    const active = !['idle','complete','cancelled'].includes(stage);
    const disabled = this._busy || d?.busy || !d?.online || !d?.inventory_ready;
    const devices = [...(d?.devices || [])].sort((a,b) => a.friendly_name.localeCompare(b.friendly_name, undefined, {numeric:true}));
    const old = devices.find(item => item.ieee_address === this._selectedOld);
    const replacement = devices.find(item => item.ieee_address === this._selectedNew);
    const groupNames = (s?.groups || []).map(g => esc(g.name));
    let content = '';
    if (!this._config.entry_id) {
      content = '<p>Configure this card with the Device Swap integration’s <code>entry_id</code>, or open <b>Replace a bulb</b> in the sidebar after adding the integration.</p>';
    } else if (!d) {
      content = '<p role="status">Connecting to Device Swap…</p>';
    } else if (!active) {
      const filtered = devices.filter(item => (item.friendly_name + ' ' + item.entities.map(e=>e.entity_id).join(' ')).toLowerCase().includes(this._query.toLowerCase()));
      content = `${stage === 'complete' ? '<p class="success" role="status">Replacement checked and complete. Ready for the next bulb.</p>' : ''}
        <h2>Which bulb needs replacing?</h2><p>Choose its existing name. We’ll save its entity IDs and groups before making changes.</p>
        <label for="search">Find a room or bulb</label><input id="search" type="search" placeholder="Kitchen, utility room…" value="${esc(this._query)}">
        <label for="old">Faulty bulb</label><select id="old">${this.options(filtered, this._selectedOld)}</select>
        <div id="old-details">${this.selectedDetails(old)}</div><div class="actions"><button data-action="flash-old" ${!old || disabled ? 'disabled':''}>Flash selected bulb</button>
        <button class="primary" data-action="begin" ${!old || disabled ? 'disabled':''}>Save and continue</button></div>`;
    } else if (stage === 'select') {
      content = `<p class="eyebrow">Replacing ${esc(s.old.friendly_name)}</p><h2>Install and pair the new bulb</h2>
        <p>Switch off the light circuit, replace the faulty bulb, then restore power. Reset the new bulb for pairing if needed.</p>
        <button data-action="pair" ${disabled || d.permit_join ? 'disabled':''}>${d.permit_join ? 'Pairing is open' : 'Open pairing for 2 minutes'}</button>
        <p class="muted">Wait for the new bulb to finish interviewing. Select it below; another device joining won’t select it for you.</p>
        <label for="replacement">Replacement bulb</label><select id="replacement">${this.options(devices.filter(item=>item.ieee_address !== s.old.ieee_address),this._selectedNew)}</select>
        ${this.selectedDetails(replacement)}<div class="actions"><button data-action="flash-new" ${!replacement || disabled ? 'disabled':''}>Flash replacement</button>
        <button class="primary" data-action="select" ${!replacement || disabled ? 'disabled':''}>Review replacement</button></div>
        <button class="text" data-action="cancel" ${disabled ? 'disabled':''}>Cancel</button>`;
    } else {
      content = `<p class="eyebrow">${stage === 'verify' ? 'Final check' : stage === 'attention' ? 'Needs attention' : 'Review replacement'}</p>
        <h2>${esc(s.old.friendly_name)}</h2><dl><dt>Remove faulty bulb</dt><dd><code>${esc(s.old.ieee_address)}</code></dd>
        <dt>Use replacement</dt><dd>${esc(s.replacement?.friendly_name)}<br><code>${esc(s.replacement?.ieee_address)}</code></dd>
        <dt>Restore groups</dt><dd>${groupNames.join(', ') || 'No groups'}</dd><dt>Keep exact HA entity IDs</dt><dd><ul class="entities">${s.entities.map(e=>`<li><code>${esc(e.entity_id)}</code></li>`).join('')}</ul></dd></dl>
        ${s.error ? `<p class="error" role="alert">${esc(s.error)}</p>`:''}
        ${stage === 'applying' || this._busy ? '<p role="status">Applying changes. This can take up to a minute. Keep the replacement powered.</p>' : ''}`;
      if (stage === 'verify') {
        content += `<p>The name, entity IDs and groups are restored. Test the replacement and your room’s normal controls or automations.</p>
          <button data-action="flash-final" ${disabled ? 'disabled':''}>Flash replacement</button>
          <label class="check"><input type="checkbox" id="confirm" ${this._confirm?'checked':''}> The correct bulb and my room controls work.</label>
          <button class="primary" data-action="finish" ${disabled || !this._confirm?'disabled':''}>Finish replacement</button>`;
      } else if (stage !== 'applying') {
        content += `<p>${stage === 'attention' ? 'Your original snapshot is saved. Check the error, then resume; completed bridge steps are checked before continuing.' : 'This will force-remove the old device, rename the replacement, restore its groups and set the entity IDs shown above.'}</p>
          <label class="check"><input type="checkbox" id="confirm" ${this._confirm?'checked':''}> I have checked both bulbs and the old bulb is disconnected.</label>
          <button class="primary" data-action="apply" ${disabled || !this._confirm?'disabled':''}>${stage === 'attention'?'Review state and resume':'Replace this bulb'}</button>
          ${stage === 'review' ? `<button class="text" data-action="cancel" ${disabled?'disabled':''}>Cancel</button>`:''}`;
      }
    }
    this.shadowRoot.innerHTML = `<style>
      :host{display:block;color:var(--primary-text-color,#202124);font-family:var(--paper-font-body1_-_font-family,Roboto,Arial,sans-serif)}
      ha-card{display:block;background:var(--card-background-color,#fff);border:1px solid var(--divider-color,#ddd);border-radius:var(--ha-card-border-radius,12px);overflow:hidden}
      .body{padding:24px;max-width:720px;margin:auto}header{display:flex;align-items:center;gap:12px;padding:20px 24px;border-bottom:1px solid var(--divider-color,#ddd)}
      header h1{font-size:20px;font-weight:500;margin:0;flex:1}.badge{font-size:12px;color:var(--secondary-text-color,#666)}
      h2{font-size:22px;font-weight:500;margin:12px 0}p{line-height:1.55;margin:12px 0}label{display:block;font-size:14px;font-weight:500;margin:18px 0 8px}
      input:not([type=checkbox]),select{box-sizing:border-box;display:block;width:100%;padding:12px;font:inherit;color:inherit;background:var(--secondary-background-color,#f5f5f5);border:1px solid var(--divider-color,#ccc);border-radius:6px;min-height:46px}
      button{font:inherit;padding:11px 16px;min-height:44px;border:1px solid var(--divider-color,#ccc);border-radius:6px;color:var(--primary-color,#03a9f4);background:transparent;cursor:pointer}
      button:disabled{opacity:.45;cursor:default}.primary{background:var(--primary-color,#0288d1);color:var(--text-primary-color,#fff);border-color:transparent}.text{border-color:transparent;margin-top:8px}
      .actions{display:flex;flex-wrap:wrap;gap:10px;margin:20px 0 0}.muted,.eyebrow{color:var(--secondary-text-color,#666)}.eyebrow{font-size:13px}
      .error{padding:12px;border-left:3px solid var(--error-color,#db4437);background:var(--secondary-background-color,#f5f5f5);overflow-wrap:anywhere}
      .success{padding:12px;border-left:3px solid var(--success-color,#388e3c)}code{font:12px/1.6 ui-monospace,SFMono-Regular,monospace;overflow-wrap:anywhere}
      dl{display:grid;grid-template-columns:160px 1fr;gap:14px;margin:24px 0}dt{font-size:13px;color:var(--secondary-text-color,#666)}dd{margin:0}.entities{max-height:180px;overflow:auto;list-style:none;padding:0;margin:0}
      .check{display:flex;gap:12px;align-items:flex-start;font-weight:400;line-height:1.5;margin:20px 0}.check input{width:20px;height:20px;flex-shrink:0;accent-color:var(--primary-color,#0288d1)}
      :focus-visible{outline:3px solid var(--primary-color,#0288d1);outline-offset:2px}
      @media(max-width:480px){.body{padding:18px}header{padding:16px}dl{grid-template-columns:1fr;gap:6px}dd{margin-bottom:10px}.actions button{flex:1}}
    </style><ha-card><header>${this._isPanel?'<button class="menu" aria-label="Open Home Assistant menu">☰</button>':''}<h1>Replace a bulb</h1><span class="badge">${d ? (d.online?'Zigbee2MQTT connected':'Offline') : ''}</span></header>
    <div class="body"><p id="error" role="alert" class="error" ${this._error?'':'hidden'}>${esc(this._error)}</p>${content}</div></ha-card>`;
    this.shadowRoot.querySelector('.menu')?.addEventListener('click',()=>this.dispatchEvent(new CustomEvent('hass-toggle-menu',{bubbles:true,composed:true})));
    this.shadowRoot.querySelector('#search')?.addEventListener('input', event => {
      this._query = event.target.value;
      this.updateSearchResults();
    });
    this.shadowRoot.querySelector('#old')?.addEventListener('change', event=> {this._selectedOld=event.target.value;this.render();});
    this.shadowRoot.querySelector('#replacement')?.addEventListener('change',event=>{this._selectedNew=event.target.value;this.render();});
    this.shadowRoot.querySelector('#confirm')?.addEventListener('change',event=>{this._confirm=event.target.checked;this.render();});
    this.shadowRoot.querySelectorAll('[data-action]').forEach(button=>button.addEventListener('click',()=>{
      const action=button.dataset.action;
      if(action.startsWith('flash-')){
        const device = action==='flash-old'?this._selectedOld:action==='flash-new'?this._selectedNew:s.replacement.ieee_address;
        this.action('flash',{device});
      } else if(action==='begin')this.action(action,{device:this._selectedOld});
      else if(action==='select')this.action(action,{device:this._selectedNew});
      else this.action(action,{confirmed:this._confirm});
    }));
  }
}

class DeviceSwapPanel extends DeviceSwapCard {
  set panel(panel) { this._isPanel = true; this.setConfig({entry_id:panel.config.entry_id}); }
  connectedCallback() { super.connectedCallback(); this.style.cssText='box-sizing:border-box;max-width:820px;margin:24px auto;padding:0 16px'; }
}
if(!customElements.get('z2m-device-swap-card'))customElements.define('z2m-device-swap-card',DeviceSwapCard);
if(!customElements.get('z2m-device-swap-panel'))customElements.define('z2m-device-swap-panel',DeviceSwapPanel);
window.customCards=window.customCards||[];
if(!window.customCards.some(card=>card.type==='z2m-device-swap-card'))window.customCards.push({type:'z2m-device-swap-card',name:'Zigbee2MQTT Device Swap',description:'Replace a bulb and restore its HA entity IDs and Zigbee groups.'});
