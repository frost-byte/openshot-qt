"""
 @file
 @brief Unit tests for ComfyTemplateRegistry's extra_inputs template-schema parsing.
"""
import json
import os
import sys
import tempfile
import types
import unittest
from unittest.mock import patch


PATH = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
if PATH not in sys.path:
    sys.path.append(PATH)

from classes.comfy_templates import ComfyTemplateRegistry


class ParseExtraInputsTests(unittest.TestCase):
    def setUp(self):
        self.registry = ComfyTemplateRegistry()

    def test_valid_entries_across_all_four_types_are_kept(self):
        payload = {
            "extra_inputs": [
                {"key": "end_clip", "type": "video", "label": "End clip", "required": True},
                {"key": "ref_photo", "type": "image", "label": "Reference photo", "required": False},
                {"key": "voice_sample", "type": "audio", "label": "Voice sample"},
                {"key": "scene_note", "type": "text", "label": "Scene detail", "required": False},
            ],
        }
        result = self.registry._parse_extra_inputs(payload, "some_template.json", needs_reference_image=False)
        self.assertEqual(
            result,
            [
                {"key": "end_clip", "type": "video", "label": "End clip", "required": True},
                {"key": "ref_photo", "type": "image", "label": "Reference photo", "required": False},
                {"key": "voice_sample", "type": "audio", "label": "Voice sample", "required": True},
                {"key": "scene_note", "type": "text", "label": "Scene detail", "required": False},
            ],
        )

    def test_bundle_type_entry_is_kept(self):
        """Regression test: the "bundle" extra_inputs type (a Reference Bundle picker,
        windows/generate.py's _populate_bundle_combo) was added to the Generate dialog's
        rendering logic without also adding it here -- EXTRA_INPUT_TYPES still only listed
        the original four types, so any "bundle" entry was silently dropped with a warning,
        making e.g. the bridge-with-bundle-voice template's voice picker never appear."""
        payload = {
            "extra_inputs": [
                {"key": "bundle_id", "type": "bundle", "label": "Voice Reference", "required": False},
            ],
        }
        result = self.registry._parse_extra_inputs(payload, "some_template.json", needs_reference_image=False)
        self.assertEqual(
            result,
            [{"key": "bundle_id", "type": "bundle", "label": "Voice Reference", "required": False}],
        )

    def test_text_entry_with_string_default_keeps_it(self):
        payload = {
            "extra_inputs": [
                {"key": "subject", "type": "text", "label": "Subject", "default": "the central subject"},
            ],
        }
        result = self.registry._parse_extra_inputs(payload, "t.json", needs_reference_image=False)
        self.assertEqual(
            result,
            [{"key": "subject", "type": "text", "label": "Subject", "required": True,
              "default": "the central subject"}],
        )

    def test_text_entry_with_empty_or_non_string_default_omits_it(self):
        payload = {
            "extra_inputs": [
                {"key": "a", "type": "text", "label": "A", "default": ""},
                {"key": "b", "type": "text", "label": "B", "default": 123},
            ],
        }
        result = self.registry._parse_extra_inputs(payload, "t.json", needs_reference_image=False)
        self.assertNotIn("default", result[0])
        self.assertNotIn("default", result[1])

    def test_group_and_group_label_are_passed_through(self):
        payload = {
            "extra_inputs": [
                {"key": "composition_name", "type": "text", "group": "scene_cast", "group_label": "Scene Cast"},
                {"key": "cast_entries_json", "type": "text", "group": "scene_cast", "default": "[]"},
            ],
        }
        result = self.registry._parse_extra_inputs(payload, "t.json", needs_reference_image=False)
        self.assertEqual(result[0]["group"], "scene_cast")
        self.assertEqual(result[0]["group_label"], "Scene Cast")
        self.assertEqual(result[1]["group"], "scene_cast")
        self.assertNotIn("group_label", result[1])

    def test_entries_without_group_omit_the_key_entirely(self):
        payload = {"extra_inputs": [{"key": "a", "type": "text", "label": "A"}]}
        result = self.registry._parse_extra_inputs(payload, "t.json", needs_reference_image=False)
        self.assertNotIn("group", result[0])
        self.assertNotIn("group_label", result[0])

    def test_non_text_entry_ignores_default(self):
        payload = {
            "extra_inputs": [
                {"key": "photo", "type": "image", "label": "Photo", "default": "ignored"},
            ],
        }
        result = self.registry._parse_extra_inputs(payload, "t.json", needs_reference_image=False)
        self.assertNotIn("default", result[0])

    def test_choice_entry_with_valid_choices_and_default_is_kept(self):
        payload = {
            "extra_inputs": [
                {"key": "n", "type": "choice", "label": "N", "choices": ["5", "22", "39"], "default": "22"},
            ],
        }
        result = self.registry._parse_extra_inputs(payload, "t.json", needs_reference_image=False)
        self.assertEqual(
            result,
            [{"key": "n", "type": "choice", "label": "N", "required": True,
              "choices": ["5", "22", "39"], "default": "22"}],
        )

    def test_choice_entry_missing_choices_is_rejected(self):
        payload = {"extra_inputs": [{"key": "n", "type": "choice", "label": "N"}]}
        result = self.registry._parse_extra_inputs(payload, "t.json", needs_reference_image=False)
        self.assertEqual(result, [])

    def test_choice_entry_empty_choices_list_is_rejected(self):
        payload = {"extra_inputs": [{"key": "n", "type": "choice", "label": "N", "choices": []}]}
        result = self.registry._parse_extra_inputs(payload, "t.json", needs_reference_image=False)
        self.assertEqual(result, [])

    def test_choice_entry_default_not_in_choices_is_dropped(self):
        payload = {
            "extra_inputs": [
                {"key": "n", "type": "choice", "label": "N", "choices": ["5", "22"], "default": "999"},
            ],
        }
        result = self.registry._parse_extra_inputs(payload, "t.json", needs_reference_image=False)
        self.assertNotIn("default", result[0])

    def test_missing_extra_inputs_key_returns_empty_list(self):
        self.assertEqual(self.registry._parse_extra_inputs({}, "t.json", needs_reference_image=False), [])

    def test_non_list_extra_inputs_is_skipped_with_warning(self):
        with patch("classes.comfy_templates.log.warning") as mock_warning:
            result = self.registry._parse_extra_inputs(
                {"extra_inputs": "not-a-list"}, "t.json", needs_reference_image=False,
            )
        self.assertEqual(result, [])
        mock_warning.assert_called_once()

    def test_non_dict_entry_is_skipped_with_warning(self):
        with patch("classes.comfy_templates.log.warning") as mock_warning:
            result = self.registry._parse_extra_inputs(
                {"extra_inputs": ["not-a-dict"]}, "t.json", needs_reference_image=False,
            )
        self.assertEqual(result, [])
        mock_warning.assert_called_once()

    def test_invalid_key_is_rejected(self):
        with patch("classes.comfy_templates.log.warning") as mock_warning:
            result = self.registry._parse_extra_inputs(
                {"extra_inputs": [{"key": "Bad Key!", "type": "video"}]}, "t.json", needs_reference_image=False,
            )
        self.assertEqual(result, [])
        mock_warning.assert_called_once()

    def test_duplicate_key_second_occurrence_is_rejected(self):
        with patch("classes.comfy_templates.log.warning") as mock_warning:
            result = self.registry._parse_extra_inputs(
                {
                    "extra_inputs": [
                        {"key": "end_clip", "type": "video"},
                        {"key": "end_clip", "type": "audio"},
                    ],
                },
                "t.json",
                needs_reference_image=False,
            )
        self.assertEqual([e["key"] for e in result], ["end_clip"])
        self.assertEqual(result[0]["type"], "video")
        mock_warning.assert_called_once()

    def test_invalid_type_is_rejected(self):
        with patch("classes.comfy_templates.log.warning") as mock_warning:
            result = self.registry._parse_extra_inputs(
                {"extra_inputs": [{"key": "thing", "type": "nonsense"}]}, "t.json", needs_reference_image=False,
            )
        self.assertEqual(result, [])
        mock_warning.assert_called_once()

    def test_missing_label_is_auto_derived_from_key(self):
        result = self.registry._parse_extra_inputs(
            {"extra_inputs": [{"key": "scene_note", "type": "text"}]}, "t.json", needs_reference_image=False,
        )
        self.assertEqual(result[0]["label"], "Scene note")

    def test_required_defaults_true_and_non_bool_is_coerced_true(self):
        result = self.registry._parse_extra_inputs(
            {
                "extra_inputs": [
                    {"key": "a", "type": "text"},
                    {"key": "b", "type": "text", "required": "yes"},
                    {"key": "c", "type": "text", "required": False},
                ],
            },
            "t.json",
            needs_reference_image=False,
        )
        self.assertEqual([e["required"] for e in result], [True, True, False])

    def test_needs_reference_image_synthesizes_entry_when_absent(self):
        result = self.registry._parse_extra_inputs({}, "video2video-basic.json", needs_reference_image=True)
        self.assertEqual(
            result,
            [{"key": "reference_image", "type": "image", "label": "Reference image", "required": True}],
        )

    def test_needs_reference_image_does_not_duplicate_explicit_entry(self):
        result = self.registry._parse_extra_inputs(
            {"extra_inputs": [{"key": "reference_image", "type": "image", "label": "Custom label"}]},
            "t.json",
            needs_reference_image=True,
        )
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["label"], "Custom label")

    def test_needs_reference_image_false_does_not_synthesize(self):
        result = self.registry._parse_extra_inputs({}, "t.json", needs_reference_image=False)
        self.assertEqual(result, [])


class LoadTemplateDefaultPromptTests(unittest.TestCase):
    def setUp(self):
        self.registry = ComfyTemplateRegistry()

    def _write_template(self, tmp_dir, payload):
        path = os.path.join(tmp_dir, "t.json")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(payload, fh)
        return path

    def test_default_prompt_is_parsed_and_stripped(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = self._write_template(tmp_dir, {
                "name": "Test",
                "default_prompt": "  S1 is here.  ",
                "workflow": {"1": {"class_type": "SaveImage", "inputs": {}}},
            })
            result = self.registry._load_template(path, is_user=False, existing_ids=set())
            self.assertEqual(result["default_prompt"], "S1 is here.")

    def test_missing_default_prompt_defaults_to_empty_string(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = self._write_template(tmp_dir, {
                "name": "Test",
                "workflow": {"1": {"class_type": "SaveImage", "inputs": {}}},
            })
            result = self.registry._load_template(path, is_user=False, existing_ids=set())
            self.assertEqual(result["default_prompt"], "")


class LoadTemplateSceneCastOpenDialogTests(unittest.TestCase):
    """A scene_cast-grouped extra_inputs entry can only ever be filled in through
    GenerateMediaDialog's builder -- open_dialog must always come back True for such a
    template, regardless of what (or whether) the template itself declares."""

    def setUp(self):
        self.registry = ComfyTemplateRegistry()

    def _write_template(self, tmp_dir, payload):
        path = os.path.join(tmp_dir, "t.json")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(payload, fh)
        return path

    def test_scene_cast_template_forces_open_dialog_true_when_unset(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = self._write_template(tmp_dir, {
                "name": "Test",
                "extra_inputs": [{"key": "composition_name", "type": "text", "group": "scene_cast"}],
                "workflow": {"1": {"class_type": "SaveVideo", "inputs": {}}},
            })
            result = self.registry._load_template(path, is_user=False, existing_ids=set())
            self.assertIs(result["open_dialog"], True)

    def test_scene_cast_template_forces_open_dialog_true_even_if_explicitly_false(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = self._write_template(tmp_dir, {
                "name": "Test",
                "open_dialog": False,
                "extra_inputs": [{"key": "composition_name", "type": "text", "group": "scene_cast"}],
                "workflow": {"1": {"class_type": "SaveVideo", "inputs": {}}},
            })
            result = self.registry._load_template(path, is_user=False, existing_ids=set())
            self.assertIs(result["open_dialog"], True)

    def test_non_scene_cast_template_open_dialog_unaffected(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = self._write_template(tmp_dir, {
                "name": "Test",
                "extra_inputs": [{"key": "some_text", "type": "text"}],
                "workflow": {"1": {"class_type": "SaveVideo", "inputs": {}}},
            })
            result = self.registry._load_template(path, is_user=False, existing_ids=set())
            self.assertIsNone(result["open_dialog"])


class HasSceneCastGroupTests(unittest.TestCase):
    def test_true_when_any_entry_has_scene_cast_group(self):
        template = {"extra_inputs": [
            {"key": "a", "type": "text"},
            {"key": "composition_name", "type": "text", "group": "scene_cast"},
        ]}
        self.assertTrue(ComfyTemplateRegistry.has_scene_cast_group(template))

    def test_false_when_no_entries_have_the_group(self):
        template = {"extra_inputs": [{"key": "a", "type": "text"}]}
        self.assertFalse(ComfyTemplateRegistry.has_scene_cast_group(template))

    def test_false_when_no_extra_inputs_key(self):
        self.assertFalse(ComfyTemplateRegistry.has_scene_cast_group({}))


class TemplatesForContextSceneCastExemptionTests(unittest.TestCase):
    """A scene_cast-grouped template is eligible for "Create with AI" (no file selected)
    AND "Enhance with AI" (a file selected) regardless of its own stored "category" --
    only the selected file is used, never as a real template input, so there is no reason
    a from-scratch Composition generation should require a file to be selected first."""

    def setUp(self):
        self.registry = ComfyTemplateRegistry()
        self.scene_cast_template = {
            "id": "video-scene-cast-generate",
            "category": "enhance",
            "input_types": [],
            "extra_inputs": [{"key": "composition_name", "type": "text", "group": "scene_cast"}],
        }
        self.plain_enhance_template = {"id": "video2video", "category": "enhance", "input_types": ["video"]}
        self.plain_create_template = {"id": "txt2img", "category": "create", "input_types": []}

    def test_scene_cast_template_included_with_no_source_file(self):
        with patch.object(self.registry, "discover", return_value=[
            self.scene_cast_template, self.plain_enhance_template, self.plain_create_template,
        ]):
            result = self.registry.templates_for_context(source_file=None)
        ids = {t["id"] for t in result}
        self.assertIn("video-scene-cast-generate", ids)
        self.assertIn("txt2img", ids)
        self.assertNotIn("video2video", ids)

    def test_scene_cast_template_included_with_source_file(self):
        source_file = types.SimpleNamespace(data={"media_type": "audio"})
        with patch.object(self.registry, "discover", return_value=[
            self.scene_cast_template, self.plain_enhance_template, self.plain_create_template,
        ]):
            result = self.registry.templates_for_context(source_file=source_file)
        ids = {t["id"] for t in result}
        self.assertIn("video-scene-cast-generate", ids)
        self.assertNotIn("video2video", ids)  # media_type mismatch (video vs audio)
        self.assertNotIn("txt2img", ids)


if __name__ == "__main__":
    unittest.main()
