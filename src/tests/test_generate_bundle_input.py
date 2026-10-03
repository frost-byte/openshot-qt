"""Unit tests for GenerateMediaDialog's "bundle" extra_inputs type (windows/generate.py) --
a Reference Bundle picker (REST-backed via fbtools_client.list_bundles(), not a Project
Files media combo) for hand-built templates that take a bundle id directly, such as a
Bridge Clips variant that wires a subject's own voice reference into the generation
instead of extracting audio from the footage itself."""

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock

SOURCE_ROOT = str(Path(__file__).resolve().parents[1])
if SOURCE_ROOT not in sys.path:
    sys.path.insert(0, SOURCE_ROOT)


class DummySettings:
    def __init__(self):
        self.values = {}

    def get(self, key):
        return self.values.get(key)

    def set(self, key, value):
        self.values[key] = value


# windows.generate transitively imports windows.region -> classes.metrics, which reads
# get_app().get_settings() at MODULE import time -- the app/settings must exist before the
# first import of windows.generate anywhere in the test process.
from qt_api import QApplication, QComboBox
from tests.qt_test_app import get_or_create_app, ensure_app_state

_app, _ = get_or_create_app(lambda: QApplication([]))
ensure_app_state(_app, DummySettings)

import windows.generate as generate_module

GenerateMediaDialog = generate_module.GenerateMediaDialog


def _bundle_template(default_value=None, required=True):
    entry = {"key": "bundle_id", "type": "bundle", "label": "Voice Reference", "required": required}
    if default_value is not None:
        entry["default"] = default_value
    return [{"id": "t1", "name": "Bridge With Bundle Voice", "template": {"extra_inputs": [entry]}}]


def _fake_client(bundles=None):
    client = MagicMock()
    client.list_bundles.return_value = bundles or []
    return client


class BundleInputTests(unittest.TestCase):
    def test_bundle_combo_populated_from_client(self):
        client = _fake_client(bundles=[{"id": "rora_k_lech", "name": "Rora (K-Lech)"}])
        dlg = GenerateMediaDialog(templates=_bundle_template(), fbtools_client=client)
        widget, _ = dlg._extra_input_widgets["bundle_id"]
        self.assertIsInstance(widget, QComboBox)
        labels = [widget.itemText(i) for i in range(widget.count())]
        self.assertIn("Rora (K-Lech)", labels)
        self.assertIn("(none)", labels)

    def test_no_client_degrades_to_placeholder_only(self):
        dlg = GenerateMediaDialog(templates=_bundle_template(), fbtools_client=None)
        widget, _ = dlg._extra_input_widgets["bundle_id"]
        self.assertEqual(widget.count(), 1)  # just "(none)"

    def test_list_bundles_failure_does_not_crash(self):
        client = _fake_client()
        client.list_bundles.side_effect = RuntimeError("fbTools unreachable")
        dlg = GenerateMediaDialog(templates=_bundle_template(), fbtools_client=client)
        widget, _ = dlg._extra_input_widgets["bundle_id"]
        self.assertEqual(widget.count(), 1)  # just "(none)", no crash

    def test_default_value_preselects_combo(self):
        client = _fake_client(bundles=[
            {"id": "rora_k_lech", "name": "Rora (K-Lech)"},
            {"id": "big_male_orc", "name": "Big Male (Orc)"},
        ])
        dlg = GenerateMediaDialog(templates=_bundle_template(default_value="big_male_orc"), fbtools_client=client)
        widget, _ = dlg._extra_input_widgets["bundle_id"]
        self.assertEqual(widget.currentData(), "big_male_orc")

    def test_selected_bundle_routed_to_text_values_not_file_ids(self):
        client = _fake_client(bundles=[{"id": "rora_k_lech", "name": "Rora (K-Lech)"}])
        dlg = GenerateMediaDialog(templates=_bundle_template(), fbtools_client=client)
        widget, _ = dlg._extra_input_widgets["bundle_id"]
        widget.setCurrentIndex(widget.findData("rora_k_lech"))
        file_ids, text_values = dlg._collect_extra_input_values()
        self.assertEqual(text_values.get("bundle_id"), "rora_k_lech")
        self.assertNotIn("bundle_id", file_ids)

    def test_unselected_bundle_is_empty_string(self):
        client = _fake_client(bundles=[{"id": "rora_k_lech", "name": "Rora (K-Lech)"}])
        dlg = GenerateMediaDialog(templates=_bundle_template(), fbtools_client=client)
        _file_ids, text_values = dlg._collect_extra_input_values()
        self.assertEqual(text_values.get("bundle_id"), "")

    def test_required_empty_bundle_flagged_as_missing(self):
        client = _fake_client(bundles=[{"id": "rora_k_lech", "name": "Rora (K-Lech)"}])
        dlg = GenerateMediaDialog(templates=_bundle_template(required=True), fbtools_client=client)
        missing = dlg._first_missing_required_input()
        self.assertIsNotNone(missing)
        widget, entry = missing
        self.assertEqual(entry["key"], "bundle_id")

    def test_optional_empty_bundle_not_flagged_as_missing(self):
        client = _fake_client(bundles=[{"id": "rora_k_lech", "name": "Rora (K-Lech)"}])
        dlg = GenerateMediaDialog(templates=_bundle_template(required=False), fbtools_client=client)
        self.assertIsNone(dlg._first_missing_required_input())


if __name__ == "__main__":
    unittest.main()
