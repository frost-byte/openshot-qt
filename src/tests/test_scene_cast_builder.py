"""Unit tests for the Scene Cast builder dialog (windows/scene_cast_builder.py), used by
GenerateMediaDialog's grouped "Scene Cast" widget for from-scratch AI generations driven by an
fbTools Composition."""

import json
from pathlib import Path
import sys
import unittest
from unittest.mock import MagicMock

SOURCE_ROOT = str(Path(__file__).resolve().parents[1])
if SOURCE_ROOT not in sys.path:
    sys.path.insert(0, SOURCE_ROOT)

from qt_api import QApplication
from tests.qt_test_app import get_or_create_app

import windows.scene_cast_builder as scb


# ── Pure functions (no Qt needed) ───────────────────────────────────────────────

class OrderedAssignedSlotsTests(unittest.TestCase):
    def test_skips_unassigned_slots(self):
        composition = {"subjects": {"A": "alex", "B": "", "C": "sam"}}
        self.assertEqual(scb.ordered_assigned_slots(composition), [("A", "alex"), ("C", "sam")])

    def test_preserves_insertion_order_not_sorted(self):
        # "AA" < "Z" as plain strings but Z (26th letter) comes first by insertion order.
        composition = {"subjects": {"Z": "z_subject", "AA": "aa_subject"}}
        self.assertEqual(scb.ordered_assigned_slots(composition), [("Z", "z_subject"), ("AA", "aa_subject")])

    def test_none_composition_returns_empty(self):
        self.assertEqual(scb.ordered_assigned_slots(None), [])

    def test_missing_subjects_key_returns_empty(self):
        self.assertEqual(scb.ordered_assigned_slots({"id": "comp"}), [])


class SortBundlesForSubjectTests(unittest.TestCase):
    def test_matching_subject_bundles_come_first(self):
        bundles = [
            {"id": "b_other", "subject_id": "sam", "name": "Zed"},
            {"id": "b_alex_1", "subject_id": "alex", "name": "Casual"},
            {"id": "b_alex_2", "subject_id": "alex", "name": "Formal"},
        ]
        result = scb.sort_bundles_for_subject(bundles, "alex")
        self.assertEqual([b["id"] for b in result], ["b_alex_1", "b_alex_2", "b_other"])

    def test_non_matching_bundles_sorted_by_name(self):
        bundles = [
            {"id": "b2", "subject_id": "sam", "name": "Zed"},
            {"id": "b1", "subject_id": "sam", "name": "Alpha"},
        ]
        result = scb.sort_bundles_for_subject(bundles, "alex")
        self.assertEqual([b["id"] for b in result], ["b1", "b2"])

    def test_non_list_input_returns_empty(self):
        self.assertEqual(scb.sort_bundles_for_subject(None, "alex"), [])


class ParseJsonHelpersTests(unittest.TestCase):
    def test_parse_cast_entries_json_valid(self):
        self.assertEqual(scb.parse_cast_entries_json('[{"subject_id": "a"}]'), [{"subject_id": "a"}])

    def test_parse_cast_entries_json_malformed_returns_empty(self):
        self.assertEqual(scb.parse_cast_entries_json("not json"), [])

    def test_parse_cast_entries_json_non_list_returns_empty(self):
        self.assertEqual(scb.parse_cast_entries_json('{"a": 1}'), [])

    def test_parse_overrides_json_valid(self):
        self.assertEqual(scb.parse_overrides_json('{"background": "cafe"}'), {"background": "cafe"})

    def test_parse_overrides_json_malformed_returns_empty_dict(self):
        self.assertEqual(scb.parse_overrides_json("not json"), {})


class BuildCastEntriesJsonTests(unittest.TestCase):
    def test_skips_assignments_without_bundle(self):
        result = json.loads(scb.build_cast_entries_json([
            {"subject_id": "alex", "bundle_id": "", "primary": False},
            {"subject_id": "sam", "bundle_id": "sam_bundle", "primary": True},
        ]))
        self.assertEqual(result, [{"subject_id": "sam", "bundle_id": "sam_bundle", "primary": True}])

    def test_primary_false_omits_primary_key(self):
        result = json.loads(scb.build_cast_entries_json([
            {"subject_id": "alex", "bundle_id": "alex_bundle", "primary": False},
        ]))
        self.assertEqual(result, [{"subject_id": "alex", "bundle_id": "alex_bundle"}])

    def test_empty_assignments_yields_empty_array(self):
        self.assertEqual(scb.build_cast_entries_json([]), "[]")


class BuildOverridesJsonTests(unittest.TestCase):
    def test_default_sentinel_omits_background_key(self):
        result = json.loads(scb.build_overrides_json(scb._USE_COMPOSITION_DEFAULT, False))
        self.assertEqual(result, {})

    def test_explicit_none_background_included(self):
        result = json.loads(scb.build_overrides_json("none", False))
        self.assertEqual(result, {"background": "none"})

    def test_background_id_included(self):
        result = json.loads(scb.build_overrides_json("cafe_interior", False))
        self.assertEqual(result, {"background": "cafe_interior"})

    def test_background_as_reference_true_included(self):
        result = json.loads(scb.build_overrides_json(scb._USE_COMPOSITION_DEFAULT, True))
        self.assertEqual(result, {"background_as_reference": True})

    def test_background_as_reference_false_omitted(self):
        result = json.loads(scb.build_overrides_json("cafe_interior", False))
        self.assertEqual(result, {"background": "cafe_interior"})
        self.assertNotIn("background_as_reference", result)


# ── Dialog-level tests (real Qt widgets) ────────────────────────────────────────

def _fake_client(compositions=None, bundles=None, backgrounds=None, composition_by_id=None):
    client = MagicMock()
    client.list_compositions.return_value = compositions or []
    client.list_bundles.return_value = bundles or []
    client.list_backgrounds.return_value = backgrounds or []
    client.get_composition.side_effect = lambda cid: (composition_by_id or {}).get(cid)
    return client


class SceneCastBuilderDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app, _ = get_or_create_app(lambda: QApplication([]))

    def test_composition_combo_populated_from_client(self):
        client = _fake_client(compositions=[{"id": "wide_shot", "name": "Wide Shot"}])
        dlg = scb.SceneCastBuilderDialog(fbtools_client=client)
        labels = [dlg.composition_combo.itemText(i) for i in range(dlg.composition_combo.count())]
        self.assertIn("Wide Shot", labels)

    def test_none_client_degrades_to_empty_combos_without_crashing(self):
        dlg = scb.SceneCastBuilderDialog(fbtools_client=None)
        self.assertEqual(dlg.composition_combo.count(), 1)  # just the placeholder
        self.assertEqual(dlg.cast_entries_json(), "[]")
        self.assertEqual(dlg.composition_overrides_json(), "{}")

    def test_selecting_composition_builds_slot_rows(self):
        client = _fake_client(
            compositions=[{"id": "wide_shot", "name": "Wide Shot"}],
            bundles=[{"id": "alex_casual", "subject_id": "alex", "name": "Casual"}],
            composition_by_id={"wide_shot": {"id": "wide_shot", "subjects": {"A": "alex", "B": "sam"}}},
        )
        dlg = scb.SceneCastBuilderDialog(fbtools_client=client)
        index = dlg.composition_combo.findData("wide_shot")
        dlg.composition_combo.setCurrentIndex(index)
        self.assertEqual(set(dlg._slot_widgets.keys()), {"A", "B"})
        self.assertEqual(dlg._slot_widgets["A"]["subject_id"], "alex")

    def test_initial_composition_name_preselects_and_loads_slots(self):
        client = _fake_client(
            compositions=[{"id": "wide_shot", "name": "Wide Shot"}],
            composition_by_id={"wide_shot": {"id": "wide_shot", "subjects": {"A": "alex"}}},
        )
        dlg = scb.SceneCastBuilderDialog(fbtools_client=client, composition_name="wide_shot")
        self.assertEqual(dlg.composition_name(), "wide_shot")
        self.assertIn("A", dlg._slot_widgets)

    def test_initial_cast_entries_preselect_bundle_and_primary(self):
        client = _fake_client(
            compositions=[{"id": "wide_shot", "name": "Wide Shot"}],
            bundles=[{"id": "alex_casual", "subject_id": "alex", "name": "Casual"}],
            composition_by_id={"wide_shot": {"id": "wide_shot", "subjects": {"A": "alex"}}},
        )
        initial_entries = json.dumps([{"subject_id": "alex", "bundle_id": "alex_casual", "primary": True}])
        dlg = scb.SceneCastBuilderDialog(
            fbtools_client=client, composition_name="wide_shot", cast_entries_json=initial_entries,
        )
        slot = dlg._slot_widgets["A"]
        self.assertEqual(slot["bundle_combo"].currentData(), "alex_casual")
        self.assertTrue(slot["primary_radio"].isChecked())
        self.assertEqual(
            json.loads(dlg.cast_entries_json()),
            [{"subject_id": "alex", "bundle_id": "alex_casual", "primary": True}],
        )

    def test_initial_overrides_preselect_background(self):
        client = _fake_client(
            compositions=[{"id": "wide_shot", "name": "Wide Shot"}],
            backgrounds=[{"id": "cafe_interior", "name": "Cafe Interior"}],
            composition_by_id={"wide_shot": {"id": "wide_shot", "subjects": {}}},
        )
        initial_overrides = json.dumps({"background": "cafe_interior", "background_as_reference": True})
        dlg = scb.SceneCastBuilderDialog(
            fbtools_client=client, composition_name="wide_shot",
            composition_overrides_json=initial_overrides,
        )
        self.assertEqual(dlg.background_combo.currentData(), "cafe_interior")
        self.assertTrue(dlg.background_as_reference_check.isChecked())
        self.assertEqual(
            json.loads(dlg.composition_overrides_json()),
            {"background": "cafe_interior", "background_as_reference": True},
        )

    def test_switching_composition_rebuilds_slots_and_clears_previous(self):
        client = _fake_client(
            compositions=[{"id": "a", "name": "A"}, {"id": "b", "name": "B"}],
            composition_by_id={
                "a": {"id": "a", "subjects": {"A": "alex"}},
                "b": {"id": "b", "subjects": {"B": "sam"}},
            },
        )
        dlg = scb.SceneCastBuilderDialog(fbtools_client=client)
        dlg.composition_combo.setCurrentIndex(dlg.composition_combo.findData("a"))
        self.assertEqual(set(dlg._slot_widgets.keys()), {"A"})
        dlg.composition_combo.setCurrentIndex(dlg.composition_combo.findData("b"))
        self.assertEqual(set(dlg._slot_widgets.keys()), {"B"})

    def test_get_composition_failure_does_not_crash(self):
        client = _fake_client(compositions=[{"id": "wide_shot", "name": "Wide Shot"}])
        client.get_composition.side_effect = RuntimeError("fbTools unreachable")
        dlg = scb.SceneCastBuilderDialog(fbtools_client=client)
        dlg.composition_combo.setCurrentIndex(dlg.composition_combo.findData("wide_shot"))
        self.assertEqual(dlg._slot_widgets, {})


if __name__ == "__main__":
    unittest.main()
