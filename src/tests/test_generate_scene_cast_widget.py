"""Unit tests for GenerateMediaDialog's grouped "Scene Cast" extra_inputs widget
(windows/generate.py) -- the entry point into the Scene Cast builder dialog for a
from-scratch AI generation driven by an fbTools Composition."""

import json
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import MagicMock, patch

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
# first import of windows.generate anywhere in the test process (same ordering constraint
# test_about.py already works around for a different dialog).
from qt_api import QApplication, QDialog
from tests.qt_test_app import get_or_create_app, ensure_app_state

_app, _ = get_or_create_app(lambda: QApplication([]))
ensure_app_state(_app, DummySettings)

import windows.generate as generate_module

GenerateMediaDialog = generate_module.GenerateMediaDialog


def _scene_cast_template(extra_group_label=None):
    entries = [
        {"key": "composition_name", "type": "text", "group": "scene_cast"},
        {"key": "cast_entries_json", "type": "text", "group": "scene_cast", "default": "[]"},
        {"key": "composition_overrides_json", "type": "text", "group": "scene_cast", "default": "{}"},
    ]
    if extra_group_label:
        entries[0]["group_label"] = extra_group_label
    return [{"id": "t1", "name": "Scene Cast Generate", "template": {"extra_inputs": entries}}]


def _source_profile_scene_cast_template():
    entries = [
        {"key": "source_profile_id", "type": "text", "group": "scene_cast", "group_label": "Scene Cast (Source Profile)"},
        {"key": "clip_id", "type": "text", "group": "scene_cast"},
        {"key": "cast_entries_json", "type": "text", "group": "scene_cast", "default": "[]"},
    ]
    return [{"id": "t3", "name": "Scene Cast Generate (Source Profile)", "template": {"extra_inputs": entries}}]


class SceneCastWidgetTests(unittest.TestCase):
    def test_grouped_entries_build_one_summary_row_not_three_text_fields(self):
        dlg = GenerateMediaDialog(templates=_scene_cast_template())
        self.assertEqual(dlg._extra_input_form.rowCount(), 1)
        self.assertIn("composition_name", dlg._extra_input_widgets)
        self.assertIn("cast_entries_json", dlg._extra_input_widgets)
        self.assertIn("composition_overrides_json", dlg._extra_input_widgets)
        # Hidden widgets, not visible QLineEdits in the form.
        for key in ("composition_name", "cast_entries_json", "composition_overrides_json"):
            widget, _entry = dlg._extra_input_widgets[key]
            self.assertFalse(widget.isVisible())

    def test_defaults_applied_when_template_omits_them(self):
        dlg = GenerateMediaDialog(templates=_scene_cast_template())
        cast_widget, _ = dlg._extra_input_widgets["cast_entries_json"]
        overrides_widget, _ = dlg._extra_input_widgets["composition_overrides_json"]
        self.assertEqual(cast_widget.text(), "[]")
        self.assertEqual(overrides_widget.text(), "{}")

    def test_summary_label_reflects_cast_state(self):
        dlg = GenerateMediaDialog(templates=_scene_cast_template())
        composition_widget, _ = dlg._extra_input_widgets["composition_name"]
        cast_widget, _ = dlg._extra_input_widgets["cast_entries_json"]
        composition_widget.setText("wide_shot")
        cast_widget.setText(json.dumps([{"subject_id": "alex", "bundle_id": "alex_bundle", "primary": True}]))
        dlg._refresh_scene_cast_summary()
        text = dlg.scene_cast_summary_label.text()
        self.assertIn("wide_shot", text)
        self.assertIn("alex", text)
        self.assertIn("alex_bundle", text)

    def test_empty_state_shows_no_cast_selected(self):
        dlg = GenerateMediaDialog(templates=_scene_cast_template())
        self.assertEqual(dlg.scene_cast_summary_label.text(), "No cast selected.")

    def test_group_label_customizes_row_label(self):
        from qt_api import QFormLayout
        dlg = GenerateMediaDialog(templates=_scene_cast_template(extra_group_label="Cast & Background"))
        label_item = dlg._extra_input_form.itemAt(0, QFormLayout.LabelRole)
        self.assertEqual(label_item.widget().text(), "Cast & Background")

    def test_edit_cast_accepted_writes_back_into_hidden_widgets(self):
        dlg = GenerateMediaDialog(templates=_scene_cast_template())
        fake_builder = MagicMock()
        fake_builder.exec_.return_value = QDialog.Accepted
        fake_builder.composition_name.return_value = "wide_shot"
        fake_builder.cast_entries_json.return_value = json.dumps(
            [{"subject_id": "alex", "bundle_id": "alex_bundle", "primary": True}]
        )
        fake_builder.composition_overrides_json.return_value = json.dumps({"background": "cafe"})

        with patch.object(generate_module, "SceneCastBuilderDialog", return_value=fake_builder) as ctor:
            dlg._edit_scene_cast_clicked()

        ctor.assert_called_once()
        composition_widget, _ = dlg._extra_input_widgets["composition_name"]
        cast_widget, _ = dlg._extra_input_widgets["cast_entries_json"]
        overrides_widget, _ = dlg._extra_input_widgets["composition_overrides_json"]
        self.assertEqual(composition_widget.text(), "wide_shot")
        self.assertEqual(json.loads(cast_widget.text()), [{"subject_id": "alex", "bundle_id": "alex_bundle", "primary": True}])
        self.assertEqual(json.loads(overrides_widget.text()), {"background": "cafe"})
        self.assertIn("wide_shot", dlg.scene_cast_summary_label.text())

    def test_edit_cast_rejected_leaves_widgets_unchanged(self):
        dlg = GenerateMediaDialog(templates=_scene_cast_template())
        composition_widget, _ = dlg._extra_input_widgets["composition_name"]
        composition_widget.setText("original")
        fake_builder = MagicMock()
        fake_builder.exec_.return_value = QDialog.Rejected

        with patch.object(generate_module, "SceneCastBuilderDialog", return_value=fake_builder):
            dlg._edit_scene_cast_clicked()

        self.assertEqual(composition_widget.text(), "original")
        fake_builder.composition_name.assert_not_called()

    def test_collect_extra_input_values_round_trips_scene_cast_keys_as_plain_text(self):
        dlg = GenerateMediaDialog(templates=_scene_cast_template())
        composition_widget, _ = dlg._extra_input_widgets["composition_name"]
        composition_widget.setText("wide_shot")
        _input_file_ids, input_text_values = dlg._collect_extra_input_values()
        self.assertEqual(input_text_values["composition_name"], "wide_shot")
        self.assertEqual(input_text_values["cast_entries_json"], "[]")

    def test_ungrouped_template_still_renders_plain_text_fields(self):
        """Regression guard: a template with no scene_cast group must be completely
        unaffected by this feature."""
        templates = [{"id": "t2", "name": "Plain", "template": {"extra_inputs": [
            {"key": "some_text", "type": "text", "label": "Some Text"},
        ]}}]
        dlg = GenerateMediaDialog(templates=templates)
        widget, entry = dlg._extra_input_widgets["some_text"]
        self.assertTrue(hasattr(widget, "setPlaceholderText"))
        self.assertEqual(entry.get("group"), None)
        self.assertFalse(dlg._scene_cast_entries)

    # ---- default tab on template selection ----

    def test_scene_cast_template_defaults_to_reference_tab_not_prompt(self):
        """The Prompt tab is inert for a scene_cast-grouped template -- opening/selecting
        one should land on the Reference tab (where "Edit Cast..." lives), not an empty
        Prompt box the user has nothing to do with."""
        dlg = GenerateMediaDialog(templates=_scene_cast_template())
        self.assertIs(dlg.tabs.currentWidget(), dlg.page_reference)

    def test_non_scene_cast_template_still_defaults_to_prompt_tab(self):
        templates = [{"id": "t2", "name": "Plain", "template": {"extra_inputs": [
            {"key": "some_text", "type": "text", "label": "Some Text"},
        ]}}]
        dlg = GenerateMediaDialog(templates=templates)
        self.assertIs(dlg.tabs.currentWidget(), dlg.page_prompt)

    # ---- pre-fill ----

    def test_prefill_resolver_called_once_and_populates_widgets(self):
        resolver = MagicMock(return_value={
            "composition_name": "wide_shot", "primary_subject": "alex", "primary_bundle": "alex_bundle",
        })
        dlg = GenerateMediaDialog(templates=_scene_cast_template(), cast_metadata_resolver=resolver)
        resolver.assert_called_once()
        composition_widget, _ = dlg._extra_input_widgets["composition_name"]
        cast_widget, _ = dlg._extra_input_widgets["cast_entries_json"]
        self.assertEqual(composition_widget.text(), "wide_shot")
        self.assertEqual(
            json.loads(cast_widget.text()),
            [{"subject_id": "alex", "bundle_id": "alex_bundle", "primary": True}],
        )

    def test_prefill_not_attempted_twice_across_template_switches(self):
        resolver = MagicMock(return_value=None)
        templates = _scene_cast_template() + [{"id": "t2", "name": "Other Scene Cast", "template": {
            "extra_inputs": [
                {"key": "composition_name", "type": "text", "group": "scene_cast"},
                {"key": "cast_entries_json", "type": "text", "group": "scene_cast"},
                {"key": "composition_overrides_json", "type": "text", "group": "scene_cast"},
            ]
        }}]
        dlg = GenerateMediaDialog(templates=templates, cast_metadata_resolver=resolver)
        dlg.template_combo.setCurrentIndex(1)
        resolver.assert_called_once()

    def test_prefill_resolver_exception_does_not_crash(self):
        resolver = MagicMock(side_effect=RuntimeError("boom"))
        dlg = GenerateMediaDialog(templates=_scene_cast_template(), cast_metadata_resolver=resolver)
        self.assertEqual(dlg.scene_cast_summary_label.text(), "No cast selected.")

    def test_no_resolver_skips_prefill_silently(self):
        dlg = GenerateMediaDialog(templates=_scene_cast_template())
        self.assertEqual(dlg.scene_cast_summary_label.text(), "No cast selected.")

    def test_fbtools_client_passed_through_to_builder(self):
        client = MagicMock()
        dlg = GenerateMediaDialog(templates=_scene_cast_template(), fbtools_client=client)
        self.assertIs(dlg.fbtools_client, client)

    # ---- Generate-clicked validation UX ----

    def test_generate_clicked_with_empty_composition_focuses_edit_button_not_hidden_widget(self):
        dlg = GenerateMediaDialog(templates=_scene_cast_template())
        dlg.name_edit.setText("my_generation")
        with patch.object(generate_module, "QMessageBox") as mock_box, \
                patch.object(dlg.scene_cast_edit_button, "setFocus") as mock_set_focus:
            dlg._on_generate_clicked()
        mock_box.warning.assert_called_once()
        title, message = mock_box.warning.call_args[0][1], mock_box.warning.call_args[0][2]
        self.assertEqual(title, "Missing Input")
        self.assertIn("Edit Cast", message)
        mock_set_focus.assert_called_once()

    def test_generate_clicked_accepts_once_composition_and_cast_are_filled(self):
        dlg = GenerateMediaDialog(templates=_scene_cast_template())
        dlg.name_edit.setText("my_generation")
        composition_widget, _ = dlg._extra_input_widgets["composition_name"]
        cast_widget, _ = dlg._extra_input_widgets["cast_entries_json"]
        composition_widget.setText("wide_shot")
        cast_widget.setText(json.dumps([{"subject_id": "alex", "bundle_id": "alex_bundle"}]))
        with patch.object(dlg, "accept") as mock_accept:
            dlg._on_generate_clicked()
        mock_accept.assert_called_once()


class SceneCastSourceProfileModeTests(unittest.TestCase):
    """Source-Profile-mode scene_cast templates share the same grouped-widget machinery as
    Composition mode, but with a different key set -- mode is detected purely from which keys
    the template declares (see GenerateMediaDialog._scene_cast_mode)."""

    def test_mode_detected_from_declared_keys(self):
        dlg = GenerateMediaDialog(templates=_source_profile_scene_cast_template())
        self.assertEqual(dlg._scene_cast_mode(), "source_profile")

    def test_composition_template_still_detected_as_composition_mode(self):
        dlg = GenerateMediaDialog(templates=_scene_cast_template())
        self.assertEqual(dlg._scene_cast_mode(), "composition")

    def test_defaults_to_reference_tab_same_as_composition_mode(self):
        dlg = GenerateMediaDialog(templates=_source_profile_scene_cast_template())
        self.assertIs(dlg.tabs.currentWidget(), dlg.page_reference)

    def test_empty_state_shows_no_cast_selected(self):
        dlg = GenerateMediaDialog(templates=_source_profile_scene_cast_template())
        self.assertEqual(dlg.scene_cast_summary_label.text(), "No cast selected.")

    def test_summary_label_reflects_source_profile_cast_state(self):
        dlg = GenerateMediaDialog(templates=_source_profile_scene_cast_template())
        profile_widget, _ = dlg._extra_input_widgets["source_profile_id"]
        clip_widget, _ = dlg._extra_input_widgets["clip_id"]
        cast_widget, _ = dlg._extra_input_widgets["cast_entries_json"]
        profile_widget.setText("team_fort")
        clip_widget.setText("clip_1")
        cast_widget.setText(json.dumps([
            {"subject_id": "alex", "bundle_id": "alex_bundle", "source_profile_id": "team_fort",
             "source_subject_id": "s1", "primary": True},
        ]))
        dlg._refresh_scene_cast_summary()
        text = dlg.scene_cast_summary_label.text()
        self.assertIn("team_fort", text)
        self.assertIn("clip_1", text)
        self.assertIn("s1", text)
        self.assertIn("alex_bundle", text)

    def test_prefill_never_attempted_for_source_profile_mode(self):
        resolver = MagicMock(return_value={"composition_name": "wide_shot"})
        dlg = GenerateMediaDialog(templates=_source_profile_scene_cast_template(), cast_metadata_resolver=resolver)
        resolver.assert_not_called()
        self.assertEqual(dlg.scene_cast_summary_label.text(), "No cast selected.")

    def test_edit_cast_opens_dialog_in_source_profile_mode_and_writes_back(self):
        dlg = GenerateMediaDialog(templates=_source_profile_scene_cast_template())
        fake_builder = MagicMock()
        fake_builder.exec_.return_value = QDialog.Accepted
        fake_builder.source_profile_id.return_value = "team_fort"
        fake_builder.clip_id.return_value = "clip_1"
        fake_builder.cast_entries_json.return_value = json.dumps([
            {"subject_id": "alex", "bundle_id": "alex_bundle", "source_profile_id": "team_fort",
             "source_subject_id": "s1", "primary": True},
        ])

        with patch.object(generate_module, "SceneCastBuilderDialog", return_value=fake_builder) as ctor:
            dlg._edit_scene_cast_clicked()

        ctor.assert_called_once()
        _args, kwargs = ctor.call_args
        self.assertEqual(kwargs["mode"], "source_profile")

        profile_widget, _ = dlg._extra_input_widgets["source_profile_id"]
        clip_widget, _ = dlg._extra_input_widgets["clip_id"]
        cast_widget, _ = dlg._extra_input_widgets["cast_entries_json"]
        self.assertEqual(profile_widget.text(), "team_fort")
        self.assertEqual(clip_widget.text(), "clip_1")
        self.assertEqual(json.loads(cast_widget.text())[0]["source_subject_id"], "s1")
        self.assertIn("team_fort", dlg.scene_cast_summary_label.text())

    def test_edit_cast_rejected_leaves_widgets_unchanged(self):
        dlg = GenerateMediaDialog(templates=_source_profile_scene_cast_template())
        profile_widget, _ = dlg._extra_input_widgets["source_profile_id"]
        profile_widget.setText("original")
        fake_builder = MagicMock()
        fake_builder.exec_.return_value = QDialog.Rejected

        with patch.object(generate_module, "SceneCastBuilderDialog", return_value=fake_builder):
            dlg._edit_scene_cast_clicked()

        self.assertEqual(profile_widget.text(), "original")
        fake_builder.source_profile_id.assert_not_called()

    def test_missing_input_message_points_at_edit_cast_for_source_profile_mode_too(self):
        dlg = GenerateMediaDialog(templates=_source_profile_scene_cast_template())
        dlg.name_edit.setText("my_generation")
        with patch.object(generate_module, "QMessageBox") as mock_box, \
                patch.object(dlg.scene_cast_edit_button, "setFocus") as mock_set_focus:
            dlg._on_generate_clicked()
        mock_box.warning.assert_called_once()
        title, message = mock_box.warning.call_args[0][1], mock_box.warning.call_args[0][2]
        self.assertEqual(title, "Missing Input")
        self.assertIn("Edit Cast", message)
        mock_set_focus.assert_called_once()


if __name__ == "__main__":
    unittest.main()
