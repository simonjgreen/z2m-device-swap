"""Exercise the UI inventory projection without the HA WebSocket decorators."""
import ast
import asyncio
import importlib.util
from pathlib import Path
from types import SimpleNamespace
import unittest

ROOT = Path(__file__).parents[1] / 'custom_components/z2m_device_swap'
spec = importlib.util.spec_from_file_location('status_workflow', ROOT / 'workflow.py')
workflow = importlib.util.module_from_spec(spec)
spec.loader.exec_module(workflow)
tree = ast.parse((ROOT / 'websocket.py').read_text())
function = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'status')
namespace = {'light_features': workflow.light_features}
exec(compile(ast.Module(body=[function], type_ignores=[]), str(ROOT / 'websocket.py'), 'exec'), namespace)


class StatusTests(unittest.TestCase):
    def project(self, device):
        bridge = SimpleNamespace(status=lambda: {'devices': [device]}, entities=lambda ieee: [],
                                 hass=SimpleNamespace(states=SimpleNamespace(get=lambda entity: None)))
        runtime = {'bridge': bridge, 'workflow': SimpleNamespace(snapshot=lambda: None, lock=asyncio.Lock()),
                   'action_lock': asyncio.Lock()}
        return namespace['status'](runtime)['devices'][0]

    def test_selected_bulb_metadata_uses_catalog_make_model_and_description(self):
        device = {'ieee_address': 'sample', 'friendly_name': 'Room bulb', 'manufacturer': 'Signify',
                  'model_id': 'LCG006', 'definition': {'vendor': 'Philips', 'model': '929003666501',
                  'description': 'Hue color GU10', 'exposes': [{'type': 'light', 'features': []}]}}
        result = self.project(device)
        self.assertEqual((result['manufacturer'], result['model'], result['description']),
                         ('Philips', '929003666501', 'Hue color GU10'))

    def test_missing_catalog_metadata_falls_back_to_reported_identity(self):
        result = self.project({'ieee_address': 'sample', 'friendly_name': 'Room bulb',
                               'manufacturer': 'Reported make', 'model_id': 'Reported model',
                               'definition': {'exposes': [{'type': 'light', 'features': []}]}})
        self.assertEqual((result['manufacturer'], result['model'], result['description']),
                         ('Reported make', 'Reported model', None))
