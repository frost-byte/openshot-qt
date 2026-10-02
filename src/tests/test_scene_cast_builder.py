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


class OrderedClipSubjectsTests(unittest.TestCase):
    def test_returns_clip_subjects_in_order_with_labels_from_profile_roster(self):
        profile = {
            "subjects": [{"id": "s1", "label": "Alex"}, {"id": "s2", "label": "Sam"}],
            "clips": [{"id": "clip_1", "subjects": ["s2", "s1"]}],
        }
        self.assertEqual(
            scb.ordered_clip_subjects(profile, "clip_1"),
            [("s2", "Sam"), ("s1", "Alex")],
        )

    def test_falls_back_to_bare_id_when_subject_missing_from_roster(self):
        profile = {"subjects": [], "clips": [{"id": "clip_1", "subjects": ["s9"]}]}
        self.assertEqual(scb.ordered_clip_subjects(profile, "clip_1"), [("s9", "s9")])

    def test_unknown_clip_id_returns_empty(self):
        profile = {"subjects": [], "clips": [{"id": "clip_1", "subjects": ["s1"]}]}
        self.assertEqual(scb.ordered_clip_subjects(profile, "clip_99"), [])

    def test_none_profile_returns_empty(self):
        self.assertEqual(scb.ordered_clip_subjects(None, "clip_1"), [])

    def test_empty_clip_id_returns_empty(self):
        profile = {"subjects": [], "clips": [{"id": "clip_1", "subjects": ["s1"]}]}
        self.assertEqual(scb.ordered_clip_subjects(profile, ""), [])


class BuildSourceProfileCastEntriesJsonTests(unittest.TestCase):
    def test_skips_rows_without_a_bundle(self):
        result = json.loads(scb.build_source_profile_cast_entries_json([
            {"subject_id": "", "bundle_id": "", "source_profile_id": "team_fort", "source_subject_id": "s1"},
            {"subject_id": "alex", "bundle_id": "alex_casual", "source_profile_id": "team_fort",
             "source_subject_id": "s2", "primary": True},
        ]))
        self.assertEqual(result, [{
            "subject_id": "alex", "bundle_id": "alex_casual",
            "source_profile_id": "team_fort", "source_subject_id": "s2", "primary": True,
        }])

    def test_primary_false_omits_primary_key(self):
        result = json.loads(scb.build_source_profile_cast_entries_json([
            {"subject_id": "alex", "bundle_id": "alex_casual", "source_profile_id": "team_fort",
             "source_subject_id": "s2", "primary": False},
        ]))
        self.assertEqual(result, [{
            "subject_id": "alex", "bundle_id": "alex_casual",
            "source_profile_id": "team_fort", "source_subject_id": "s2",
        }])

    def test_missing_subject_id_skips_row(self):
        # subject_id comes from the chosen bundle's own subject_id -- an unresolvable bundle
        # (shouldn't happen via the dialog, but defensively) must not emit a broken entry.
        result = json.loads(scb.build_source_profile_cast_entries_json([
            {"subject_id": "", "bundle_id": "alex_casual", "source_profile_id": "team_fort",
             "source_subject_id": "s2"},
        ]))
        self.assertEqual(result, [])

    def test_empty_assignments_yields_empty_array(self):
        self.assertEqual(scb.build_source_profile_cast_entries_json([]), "[]")


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


def _fake_source_profile_client(profiles=None, bundles=None, profile_by_id=None):
    client = MagicMock()
    client.list_source_profiles.return_value = profiles or []
    client.list_bundles.return_value = bundles or []
    client.get_source_profile.side_effect = lambda pid: (profile_by_id or {}).get(pid)
    return client


class SceneCastBuilderDialogSourceProfileModeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app, _ = get_or_create_app(lambda: QApplication([]))

    def test_source_profile_combo_populated_from_client(self):
        client = _fake_source_profile_client(profiles=[{"id": "team_fort", "name": "Team Fort"}])
        dlg = scb.SceneCastBuilderDialog(fbtools_client=client, mode="source_profile")
        labels = [dlg.source_profile_combo.itemText(i) for i in range(dlg.source_profile_combo.count())]
        self.assertIn("Team Fort", labels)

    def test_none_client_degrades_to_empty_combos_without_crashing(self):
        dlg = scb.SceneCastBuilderDialog(fbtools_client=None, mode="source_profile")
        self.assertEqual(dlg.source_profile_combo.count(), 1)  # just the placeholder
        self.assertEqual(dlg.cast_entries_json(), "[]")
        self.assertEqual(dlg.composition_overrides_json(), "{}")

    def test_selecting_profile_populates_clip_combo(self):
        client = _fake_source_profile_client(
            profiles=[{"id": "team_fort", "name": "Team Fort"}],
            profile_by_id={"team_fort": {"id": "team_fort", "clips": [
                {"id": "clip_1", "label": "Intro"}, {"id": "clip_2", "label": "Outro"},
            ]}},
        )
        dlg = scb.SceneCastBuilderDialog(fbtools_client=client, mode="source_profile")
        dlg.source_profile_combo.setCurrentIndex(dlg.source_profile_combo.findData("team_fort"))
        labels = [dlg.clip_combo.itemText(i) for i in range(dlg.clip_combo.count())]
        self.assertIn("Intro", labels)
        self.assertIn("Outro", labels)

    def test_selecting_clip_builds_subject_rows(self):
        client = _fake_source_profile_client(
            profiles=[{"id": "team_fort", "name": "Team Fort"}],
            bundles=[{"id": "alex_casual", "subject_id": "alex", "name": "Casual"}],
            profile_by_id={"team_fort": {
                "id": "team_fort",
                "subjects": [{"id": "s1", "label": "Rora"}, {"id": "s2", "label": "Big Male"}],
                "clips": [{"id": "clip_1", "label": "Intro", "subjects": ["s1", "s2"]}],
            }},
        )
        dlg = scb.SceneCastBuilderDialog(fbtools_client=client, mode="source_profile")
        dlg.source_profile_combo.setCurrentIndex(dlg.source_profile_combo.findData("team_fort"))
        dlg.clip_combo.setCurrentIndex(dlg.clip_combo.findData("clip_1"))
        self.assertEqual(set(dlg._slot_widgets.keys()), {"s1", "s2"})
        self.assertEqual(dlg._slot_widgets["s1"]["source_subject_id"], "s1")

    def test_cast_entries_json_resolves_subject_id_from_chosen_bundle(self):
        client = _fake_source_profile_client(
            profiles=[{"id": "team_fort", "name": "Team Fort"}],
            bundles=[{"id": "alex_casual", "subject_id": "alex", "name": "Casual"}],
            profile_by_id={"team_fort": {
                "id": "team_fort",
                "subjects": [{"id": "s1", "label": "Rora"}],
                "clips": [{"id": "clip_1", "label": "Intro", "subjects": ["s1"]}],
            }},
        )
        dlg = scb.SceneCastBuilderDialog(fbtools_client=client, mode="source_profile")
        dlg.source_profile_combo.setCurrentIndex(dlg.source_profile_combo.findData("team_fort"))
        dlg.clip_combo.setCurrentIndex(dlg.clip_combo.findData("clip_1"))
        slot = dlg._slot_widgets["s1"]
        slot["bundle_combo"].setCurrentIndex(slot["bundle_combo"].findData("alex_casual"))
        slot["primary_radio"].setChecked(True)
        self.assertEqual(
            json.loads(dlg.cast_entries_json()),
            [{
                "subject_id": "alex", "bundle_id": "alex_casual",
                "source_profile_id": "team_fort", "source_subject_id": "s1", "primary": True,
            }],
        )

    def test_unchosen_bundle_rows_are_omitted_from_cast_entries(self):
        client = _fake_source_profile_client(
            profiles=[{"id": "team_fort", "name": "Team Fort"}],
            profile_by_id={"team_fort": {
                "id": "team_fort",
                "subjects": [{"id": "s1", "label": "Rora"}],
                "clips": [{"id": "clip_1", "label": "Intro", "subjects": ["s1"]}],
            }},
        )
        dlg = scb.SceneCastBuilderDialog(fbtools_client=client, mode="source_profile")
        dlg.source_profile_combo.setCurrentIndex(dlg.source_profile_combo.findData("team_fort"))
        dlg.clip_combo.setCurrentIndex(dlg.clip_combo.findData("clip_1"))
        self.assertEqual(dlg.cast_entries_json(), "[]")

    def test_initial_values_preselect_profile_clip_and_cast(self):
        client = _fake_source_profile_client(
            profiles=[{"id": "team_fort", "name": "Team Fort"}],
            bundles=[{"id": "alex_casual", "subject_id": "alex", "name": "Casual"}],
            profile_by_id={"team_fort": {
                "id": "team_fort",
                "subjects": [{"id": "s1", "label": "Rora"}],
                "clips": [{"id": "clip_1", "label": "Intro", "subjects": ["s1"]}],
            }},
        )
        initial_entries = json.dumps([{
            "subject_id": "alex", "bundle_id": "alex_casual",
            "source_profile_id": "team_fort", "source_subject_id": "s1", "primary": True,
        }])
        dlg = scb.SceneCastBuilderDialog(
            fbtools_client=client, mode="source_profile",
            source_profile_id="team_fort", clip_id="clip_1", cast_entries_json=initial_entries,
        )
        self.assertEqual(dlg.source_profile_id(), "team_fort")
        self.assertEqual(dlg.clip_id(), "clip_1")
        slot = dlg._slot_widgets["s1"]
        self.assertEqual(slot["bundle_combo"].currentData(), "alex_casual")
        self.assertTrue(slot["primary_radio"].isChecked())

    def test_composition_name_and_combo_absent_in_source_profile_mode(self):
        dlg = scb.SceneCastBuilderDialog(fbtools_client=None, mode="source_profile")
        self.assertEqual(dlg.composition_name(), "")
        self.assertFalse(hasattr(dlg, "composition_combo"))
        self.assertFalse(hasattr(dlg, "background_combo"))

    def test_get_source_profile_failure_does_not_crash(self):
        client = _fake_source_profile_client(profiles=[{"id": "team_fort", "name": "Team Fort"}])
        client.get_source_profile.side_effect = RuntimeError("fbTools unreachable")
        dlg = scb.SceneCastBuilderDialog(fbtools_client=client, mode="source_profile")
        dlg.source_profile_combo.setCurrentIndex(dlg.source_profile_combo.findData("team_fort"))
        self.assertEqual(dlg._slot_widgets, {})


if __name__ == "__main__":
    unittest.main()
