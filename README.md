# Zigbee2MQTT Device Swap

Replace a failed Zigbee bulb from Home Assistant. The integration saves the old bulb's exact HA entity IDs and Zigbee2MQTT groups, guides pairing, then applies the replacement after you review it.

Status: **early development, not yet validated with a physical replacement**. Installed on HA 2026.10.1 with Z2M 2.14.2; configuration, live inventory and panel registration have been checked. Local tests use a simulated bridge and browser preview. Physical replacement acceptance is still pending.

## Requirements

- Home Assistant 2026.10 or later (uses its current `probatio` schemas).
- Zigbee2MQTT 2.x with Home Assistant discovery enabled.
- HA's MQTT integration configured and connected to the same broker.
- An administrator account for the replacement interface.
- Single-channel light bulbs; old and replacement must expose matching entity features and group endpoints. Philips Hue bulbs with endpoint 11 plus Green Power endpoint 242 are supported by the endpoint checks.

No cloud service or separate API key is used. The installed integration reuses HA's MQTT connection; its card uses your existing HA session. A token is needed only for optional development/installation scripts.

## Install

Manual: copy `custom_components/z2m_device_swap` to your HA configuration directory's `custom_components/` folder and restart Home Assistant. Add **Zigbee2MQTT Device Swap** under Settings → Devices & services → Add integration. Enter the MQTT base topic (normally `zigbee2mqtt`).

The integration loads its bundled Lovelace card. Add the card to a normal HA dashboard so HA supplies its navigation, layout and edit controls. The integration does not create a custom sidebar panel.

HACS: add `https://github.com/simonjgreen/z2m-device-swap` under HACS → Custom repositories, category **Integration**, and install. Tests and official HACS/hassfest validation run on GitHub.

For a dashboard card, open a dashboard, choose Edit → Add card → Manual, and use:

```yaml
type: custom:z2m-device-swap-card
entry_id: YOUR_DEVICE_SWAP_CONFIG_ENTRY_ID
```

The entry ID is visible in the integration's config-entry URL or the `config_entries/get` WebSocket response. The integration loads the JavaScript automatically. If resource loading is managed manually, use `/z2m_device_swap/z2m-device-swap-card.js?v=0.1.2` as a JavaScript module resource.

For a dedicated native dashboard, the optional helper `scripts/setup_ha.py --ha-url http://YOUR_HA:8123 --dashboard` creates one containing the card. It uses HA's supported Lovelace APIs, leaves existing dashboards untouched, and preserves an existing Device Swap dashboard's edits.

## Replace one bulb

1. Choose the faulty bulb by its existing name. **Identify selected bulb** uses the bulb’s native Identify button (or an explicitly supported blink effect). A request confirmation appears after it is sent. Dead or unpowered bulbs cannot blink; identify working neighbors to locate them. HA may still show a cached on/off state for an unavailable bulb.
2. Save the snapshot. Switch off the circuit, change the hardware, and restore power.
3. Open the two-minute pairing window and reset the new bulb if needed. Select the replacement explicitly and wait for its interview and HA discovery to finish.
4. Review both device addresses, the exact HA entity IDs, and old group memberships. Confirm that the old bulb is disconnected.
5. Apply. The integration force-removes the old device, renames the replacement with `homeassistant_rename: true`, restores group membership, and restores any exact entity IDs (including custom names or suffixes).
6. Test the new bulb and the room's normal controls/automations, then finish the replacement. Start the next bulb only after this check.

## Scope and recovery

This automates the established entity-ID-and-group replacement procedure. HA internal device IDs, device-based automation references, direct Zigbee bindings, device-specific configuration, and Zigbee scenes are not migrated. A mismatched replacement entity or group endpoint stops the flow before removal. Entity-ID collisions stop rather than delete unrelated entries.

A snapshot and operation intent are saved before mutations in HA-managed storage under `z2m_device_swap.<entry_id>`. The previous 20 finished/cancelled snapshots are retained when you start a new swap. Take your normal HA/Z2M backup before the first production test. A snapshot is a recovery record, not a way to resurrect a physically dead bulb.

If a request times out or HA restarts, the flow asks for attention. Keep the replacement powered. Wait at least 35 seconds after a timeout, inspect the named bulb and groups, then resume. The workflow checks completed bridge steps instead of replaying them blindly. A started replacement cannot be discarded with Cancel; recover it using the saved snapshot. Entity restoration may wait up to 30 seconds for HA discovery/removal to settle.

Pairing windows opened here expire after two minutes. The integration does not close an existing window opened by another tool.

## Development

```sh
python3 -m unittest discover -s tests -v
python3 -m compileall -q custom_components
node --check custom_components/z2m_device_swap/frontend/z2m-device-swap-card.js
```

The Python suite covers the workflow, pre-removal guards, lost responses, failure recovery, request correlation and exact entity matching. It does not run the HA runtime.

For browser checks, serve the project locally on port 8765, start Chromium with a temporary profile and debugging port 9223, then run `scripts/check_card.py`. It uses the local `tests/card-preview.html` and never connects to HA. Helper scripts require the Python `websockets` package.

`scripts/install_ha.py --ha-url http://YOUR_HA:8123` checks installation through the File editor add-on without changing files. `--install` installs only this new integration directory and verifies every uploaded file. It refuses to overwrite an existing installation and never restarts HA. For a known installation, `--update-from COMMIT --install` first checks every remote file against that exact Git commit, backs up changed files beside their originals, and verifies each replacement. Tokens are prompted without echo and remain in memory.

See [the research notes](docs/research.md) for sources and scope.
