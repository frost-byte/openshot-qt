"""Unit tests for the Scene Cast builder dialog (windows/scene_cast_builder.py), used by
GenerateMediaDialog's grouped "Scene Cast" widget for from-scratch AI generations driven by an
fbTools Composition."""

import json
from pathlib import Path
import sys
import unittest
from unittest.mock import MagicMock, patch

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

    def test_use_audio_true_is_included_and_false_is_omitted(self):
        result = json.loads(scb.build_cast_entries_json([
            {"subject_id": "alex", "bundle_id": "alex_bundle", "use_audio": True},
            {"subject_id": "sam", "bundle_id": "sam_bundle", "use_audio": False},
        ]))
        self.assertEqual(result, [
            {"subject_id": "alex", "bundle_id": "alex_bundle", "use_audio": True},
            {"subject_id": "sam", "bundle_id": "sam_bundle"},
        ])


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


class BuildBackgroundOverrideIdTests(unittest.TestCase):
    def test_default_sentinel_returns_empty_string(self):
        self.assertEqual(scb.build_background_override_id(scb._USE_COMPOSITION_DEFAULT), "")

    def test_explicit_none_returns_none_string(self):
        self.assertEqual(scb.build_background_override_id("none"), "none")

    def test_background_id_returned_as_is(self):
        self.assertEqual(scb.build_background_override_id("rooftop"), "rooftop")


class FindClipTests(unittest.TestCase):
    def test_returns_matching_clip(self):
        profile = {"clips": [{"id": "clip_1", "action": "a"}, {"id": "clip_2", "action": "b"}]}
        self.assertEqual(scb.find_clip(profile, "clip_2"), {"id": "clip_2", "action": "b"})

    def test_returns_none_for_unknown_clip_id(self):
        profile = {"clips": [{"id": "clip_1"}]}
        self.assertIsNone(scb.find_clip(profile, "clip_9"))

    def test_none_profile_returns_none(self):
        self.assertIsNone(scb.find_clip(None, "clip_1"))

    def test_empty_clip_id_returns_none(self):
        profile = {"clips": [{"id": "clip_1"}]}
        self.assertIsNone(scb.find_clip(profile, ""))


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

    def test_use_audio_true_is_included_and_false_is_omitted(self):
        result = json.loads(scb.build_source_profile_cast_entries_json([
            {"subject_id": "alex", "bundle_id": "alex_casual", "source_profile_id": "team_fort",
             "source_subject_id": "s1", "use_audio": True},
            {"subject_id": "sam", "bundle_id": "sam_casual", "source_profile_id": "team_fort",
             "source_subject_id": "s2", "use_audio": False},
        ]))
        self.assertEqual([("use_audio" in e) for e in result], [True, False])
        self.assertTrue(result[0]["use_audio"])

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

    def _audio_dialog(self, initial_entries=None):
        client = _fake_client(
            compositions=[{"id": "wide_shot", "name": "Wide Shot"}],
            bundles=[{"id": "alex_casual", "subject_id": "alex", "name": "Casual"}],
            composition_by_id={"wide_shot": {"id": "wide_shot", "subjects": {"A": "alex"}}},
        )
        return scb.SceneCastBuilderDialog(
            fbtools_client=client, composition_name="wide_shot",
            cast_entries_json=json.dumps(initial_entries) if initial_entries is not None else "[]",
        )

    def test_audio_checkbox_is_disabled_until_a_bundle_is_chosen(self):
        dlg = self._audio_dialog()
        slot = dlg._slot_widgets["A"]
        self.assertFalse(slot["audio_check"].isEnabled())
        slot["bundle_combo"].setCurrentIndex(slot["bundle_combo"].findData("alex_casual"))
        self.assertTrue(slot["audio_check"].isEnabled())

    def test_audio_checkbox_writes_use_audio_into_the_entry(self):
        dlg = self._audio_dialog()
        slot = dlg._slot_widgets["A"]
        slot["bundle_combo"].setCurrentIndex(slot["bundle_combo"].findData("alex_casual"))
        self.assertEqual(json.loads(dlg.cast_entries_json()), [{"subject_id": "alex", "bundle_id": "alex_casual"}])
        slot["audio_check"].setChecked(True)
        self.assertEqual(
            json.loads(dlg.cast_entries_json()),
            [{"subject_id": "alex", "bundle_id": "alex_casual", "use_audio": True}],
        )

    def test_audio_checkbox_is_cleared_when_the_bundle_is_unselected(self):
        dlg = self._audio_dialog()
        slot = dlg._slot_widgets["A"]
        slot["bundle_combo"].setCurrentIndex(slot["bundle_combo"].findData("alex_casual"))
        slot["audio_check"].setChecked(True)
        slot["bundle_combo"].setCurrentIndex(0)   # back to "(use Composition default)"
        self.assertFalse(slot["audio_check"].isEnabled())
        self.assertFalse(slot["audio_check"].isChecked())
        self.assertEqual(dlg.cast_entries_json(), "[]")

    def test_initial_use_audio_is_restored_when_the_dialog_reopens(self):
        dlg = self._audio_dialog([{"subject_id": "alex", "bundle_id": "alex_casual", "use_audio": True}])
        slot = dlg._slot_widgets["A"]
        self.assertTrue(slot["audio_check"].isEnabled())
        self.assertTrue(slot["audio_check"].isChecked())
        self.assertEqual(json.loads(dlg.cast_entries_json())[0].get("use_audio"), True)

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


def _fake_source_profile_client(profiles=None, bundles=None, backgrounds=None, profile_by_id=None):
    client = MagicMock()
    client.list_source_profiles.return_value = profiles or []
    client.list_bundles.return_value = bundles or []
    client.list_backgrounds.return_value = backgrounds or []
    client.get_source_profile.side_effect = lambda pid: (profile_by_id or {}).get(pid)
    # A real-ish return (not an unconfigured MagicMock's default) so a test that lets a real
    # fetch thread run to completion doesn't risk _on_frame_fetched later choking on
    # QPixmap.loadFromData() being handed a MagicMock instead of bytes if that queued
    # cross-thread signal ever gets processed (e.g. during a later test's own event pump).
    client.get_source_profile_frame.return_value = b"fake-thumbnail-bytes"
    return client


class SceneCastBuilderDialogSourceProfileModeTests(unittest.TestCase):
    """Clip selection also kicks off an async thumbnail fetch (a real QThread hitting
    fbTools over HTTP) -- patched out here in every test via setUp/tearDown so these tests
    never spin up a real background thread or network call. See
    ClipPreviewTests below for dedicated coverage of that mechanism."""

    @classmethod
    def setUpClass(cls):
        cls.app, _ = get_or_create_app(lambda: QApplication([]))

    def setUp(self):
        self._fetch_patcher = patch.object(scb.SceneCastBuilderDialog, "_fetch_clip_thumbnail")
        self._fetch_patcher.start()

    def tearDown(self):
        self._fetch_patcher.stop()

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
        self.assertEqual(dlg.background_override_id(), "")

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

    def test_audio_checkbox_writes_use_audio_into_source_profile_entries(self):
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
        self.assertFalse(slot["audio_check"].isEnabled())
        slot["bundle_combo"].setCurrentIndex(slot["bundle_combo"].findData("alex_casual"))
        slot["audio_check"].setChecked(True)
        self.assertEqual(
            json.loads(dlg.cast_entries_json()),
            [{
                "subject_id": "alex", "bundle_id": "alex_casual",
                "source_profile_id": "team_fort", "source_subject_id": "s1", "use_audio": True,
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
        self.assertTrue(hasattr(dlg, "source_background_combo"))

    def test_background_override_combo_populated_from_client(self):
        client = _fake_source_profile_client(backgrounds=[{"id": "rooftop", "name": "Rooftop"}])
        dlg = scb.SceneCastBuilderDialog(fbtools_client=client, mode="source_profile")
        labels = [dlg.source_background_combo.itemText(i) for i in range(dlg.source_background_combo.count())]
        self.assertIn("Rooftop", labels)
        self.assertIn("(use clip/profile default)", labels)
        self.assertIn("(none, this run)", labels)

    def test_background_override_defaults_to_empty(self):
        client = _fake_source_profile_client(backgrounds=[{"id": "rooftop", "name": "Rooftop"}])
        dlg = scb.SceneCastBuilderDialog(fbtools_client=client, mode="source_profile")
        self.assertEqual(dlg.background_override_id(), "")

    def test_selecting_none_background_override(self):
        client = _fake_source_profile_client(backgrounds=[{"id": "rooftop", "name": "Rooftop"}])
        dlg = scb.SceneCastBuilderDialog(fbtools_client=client, mode="source_profile")
        dlg.source_background_combo.setCurrentIndex(dlg.source_background_combo.findData("none"))
        self.assertEqual(dlg.background_override_id(), "none")

    def test_selecting_a_background_override(self):
        client = _fake_source_profile_client(backgrounds=[{"id": "rooftop", "name": "Rooftop"}])
        dlg = scb.SceneCastBuilderDialog(fbtools_client=client, mode="source_profile")
        dlg.source_background_combo.setCurrentIndex(dlg.source_background_combo.findData("rooftop"))
        self.assertEqual(dlg.background_override_id(), "rooftop")

    def test_initial_background_override_id_preselects_combo(self):
        client = _fake_source_profile_client(backgrounds=[{"id": "rooftop", "name": "Rooftop"}])
        dlg = scb.SceneCastBuilderDialog(
            fbtools_client=client, mode="source_profile", background_override_id="rooftop",
        )
        self.assertEqual(dlg.source_background_combo.currentData(), "rooftop")
        self.assertEqual(dlg.background_override_id(), "rooftop")

    def test_initial_background_override_id_none_preselects_none_option(self):
        client = _fake_source_profile_client(backgrounds=[{"id": "rooftop", "name": "Rooftop"}])
        dlg = scb.SceneCastBuilderDialog(
            fbtools_client=client, mode="source_profile", background_override_id="none",
        )
        self.assertEqual(dlg.source_background_combo.currentData(), "none")
        self.assertEqual(dlg.background_override_id(), "none")

    def test_background_override_id_absent_in_composition_mode(self):
        dlg = scb.SceneCastBuilderDialog(fbtools_client=None, mode="composition")
        self.assertEqual(dlg.background_override_id(), "")
        self.assertFalse(hasattr(dlg, "source_background_combo"))

    def test_get_source_profile_failure_does_not_crash(self):
        client = _fake_source_profile_client(profiles=[{"id": "team_fort", "name": "Team Fort"}])
        client.get_source_profile.side_effect = RuntimeError("fbTools unreachable")
        dlg = scb.SceneCastBuilderDialog(fbtools_client=client, mode="source_profile")
        dlg.source_profile_combo.setCurrentIndex(dlg.source_profile_combo.findData("team_fort"))
        self.assertEqual(dlg._slot_widgets, {})


class ClipPreviewTests(unittest.TestCase):
    """Covers the clip-segment preview: synchronous action-text display, and the async
    thumbnail fetch mechanism (_fetch_clip_thumbnail is mocked out here too, so no real
    QThread/network call ever runs in tests -- _on_frame_fetched's own logic is exercised
    directly instead, the same way the real worker's "finished" signal would invoke it)."""

    @classmethod
    def setUpClass(cls):
        cls.app, _ = get_or_create_app(lambda: QApplication([]))

    def _dialog_on_clip(self, clip, profile_id="team_fort"):
        client = _fake_source_profile_client(
            profiles=[{"id": profile_id, "name": "Team Fort"}],
            profile_by_id={profile_id: {"id": profile_id, "subjects": [], "clips": [clip]}},
        )
        with patch.object(scb.SceneCastBuilderDialog, "_fetch_clip_thumbnail") as fetch_mock:
            dlg = scb.SceneCastBuilderDialog(fbtools_client=client, mode="source_profile")
            dlg.source_profile_combo.setCurrentIndex(dlg.source_profile_combo.findData(profile_id))
            dlg.clip_combo.setCurrentIndex(dlg.clip_combo.findData(clip["id"]))
        return dlg, fetch_mock

    def test_action_text_shown_for_selected_clip(self):
        dlg, _fetch_mock = self._dialog_on_clip({"id": "clip_1", "action": "Alex waves hello.", "start_time": 2.0})
        self.assertEqual(dlg.clip_action_label.text(), "Alex waves hello.")

    def test_missing_action_text_shows_placeholder(self):
        dlg, _fetch_mock = self._dialog_on_clip({"id": "clip_1", "start_time": 0.0})
        self.assertEqual(dlg.clip_action_label.text(), "(no action text)")

    def test_thumbnail_fetch_requested_with_clip_start_time(self):
        dlg, fetch_mock = self._dialog_on_clip({"id": "clip_1", "action": "x", "start_time": 4.5})
        fetch_mock.assert_called_once()
        profile_id, timestamp, request_id = fetch_mock.call_args[0]
        self.assertEqual(profile_id, "team_fort")
        self.assertEqual(timestamp, 4.5)
        self.assertEqual(request_id, dlg._frame_request_id)

    def test_no_client_skips_fetch_and_shows_no_preview(self):
        dlg = scb.SceneCastBuilderDialog(fbtools_client=None, mode="source_profile")
        dlg._update_clip_preview()
        self.assertEqual(dlg.clip_thumbnail_label.text(), "No preview")

    def test_fetch_thread_is_not_parented_to_dialog(self):
        """Regression test for a SIGABRT crash ("QThread: Destroyed while thread is still
        running"): the fetch thread must not be parented to this (or any ancestor) dialog,
        or Qt's child-destruction cascade tries to tear down a still-running QThread the
        moment the dialog is closed before a slow fbTools response arrives. Calls the real
        (unmocked) _fetch_clip_thumbnail -- safe here since fbtools_client is a MagicMock,
        so the worker's HTTP call returns instantly with no real network I/O."""
        client = _fake_source_profile_client(profiles=[{"id": "team_fort", "name": "Team Fort"}])
        dlg = scb.SceneCastBuilderDialog(fbtools_client=client, mode="source_profile")
        dlg._fetch_clip_thumbnail("team_fort", 1.5, dlg._frame_request_id)
        self.assertEqual(len(dlg._frame_threads), 1)
        thread, _worker = dlg._frame_threads[0]
        self.assertIsNone(thread.parent())
        self.assertTrue(thread.wait(2000), "worker thread did not finish in time")
        # The real bug this whole chain traced back to: the thread finishing (or even
        # claiming to) is NOT proof worker.run() actually executed -- if worker itself got
        # garbage collected first (no reference held anywhere but this method's own local
        # variable), thread.started never has anything to invoke and the fetch silently
        # never happens at all, with no exception and nothing in the log. The only real
        # proof is that the underlying client call was actually made.
        client.get_source_profile_frame.assert_called_once_with("team_fort", 1.5, width=scb._THUMBNAIL_WIDTH)

    def test_worker_is_kept_alive_until_its_own_thread_finishes(self):
        """Regression test: _frame_threads must track the worker alongside its thread, not
        just the thread. A worker with no other Python reference and no Qt parent is
        destroyed the instant _fetch_clip_thumbnail() returns (immediately after
        thread.start(), well before the OS schedules the new thread to actually run) unless
        something keeps it alive -- silently preventing thread.started from ever having
        anything to invoke. No exception, no log output: just a thumbnail stuck on
        "Loading..." forever. This is exactly what "stayed stuck on Loading after the crash
        fix" turned out to be."""
        client = _fake_source_profile_client(profiles=[{"id": "team_fort", "name": "Team Fort"}])
        dlg = scb.SceneCastBuilderDialog(fbtools_client=client, mode="source_profile")
        dlg._fetch_clip_thumbnail("team_fort", 1.5, dlg._frame_request_id)
        thread, worker = dlg._frame_threads[0]
        self.assertIsNotNone(worker)
        thread.wait(2000)
        client.get_source_profile_frame.assert_called_once()

    def test_overlapping_fetches_do_not_drop_an_in_flight_thread(self):
        """Regression test for the "stuck on Loading forever" bug: a second fetch starting
        before the first one's finished signal has fired must not replace the only reference
        to the still-running first thread (the old single-slot self._frame_thread did exactly
        that) -- both must stay tracked in _frame_threads until each genuinely finishes."""
        client = _fake_source_profile_client(profiles=[{"id": "team_fort", "name": "Team Fort"}])
        dlg = scb.SceneCastBuilderDialog(fbtools_client=client, mode="source_profile")
        dlg._fetch_clip_thumbnail("team_fort", 1.0, 1)
        first_pair = dlg._frame_threads[0]
        dlg._fetch_clip_thumbnail("team_fort", 2.0, 2)
        # The first (thread, worker) pair must still be tracked (not silently dropped) even
        # though a second fetch has already started -- both get a chance to finish and clean
        # themselves up.
        self.assertIn(first_pair, dlg._frame_threads)
        for thread, _worker in list(dlg._frame_threads):
            thread.wait(2000)
        self.assertEqual(client.get_source_profile_frame.call_count, 2)

    def test_select_initial_clip_fetches_thumbnail_only_once(self):
        """Regression test: _select_initial_clip() calls _on_clip_changed once via the
        combo's signal (when setCurrentIndex actually changes the index) and once directly
        (to guarantee it ran at least once, matching _on_composition_changed's own pattern)
        -- _on_clip_changed must de-duplicate those into a single thumbnail fetch, not two."""
        with patch.object(scb.SceneCastBuilderDialog, "_fetch_clip_thumbnail") as fetch_mock:
            client = _fake_source_profile_client(
                profiles=[{"id": "team_fort", "name": "Team Fort"}],
                profile_by_id={"team_fort": {
                    "id": "team_fort", "subjects": [],
                    "clips": [{"id": "clip_1", "action": "x", "start_time": 0.0}],
                }},
            )
            scb.SceneCastBuilderDialog(
                fbtools_client=client, mode="source_profile",
                source_profile_id="team_fort", clip_id="clip_1",
            )
        fetch_mock.assert_called_once()

    def test_on_frame_fetched_sets_pixmap_for_current_request(self):
        dlg, _fetch_mock = self._dialog_on_clip({"id": "clip_1", "action": "x", "start_time": 0.0})
        # A real JPEG is overkill here -- loadFromData() failing on bogus bytes is exactly
        # the "No preview" fallback path, covered separately below. Use a real 1x1 pixmap's
        # own PNG bytes instead, which QPixmap can decode regardless of the JPEG-ness fbTools
        # actually sends in production (loadFromData() auto-detects format).
        from qt_api import QPixmap, QBuffer
        px = QPixmap(1, 1)
        buf = QBuffer()
        buf.open(QBuffer.ReadWrite)
        px.save(buf, "PNG")
        data = bytes(buf.data())
        dlg._on_frame_fetched(dlg._frame_request_id, data)
        self.assertFalse(dlg.clip_thumbnail_label.pixmap().isNull())

    def test_on_frame_fetched_ignores_stale_request_id(self):
        dlg, _fetch_mock = self._dialog_on_clip({"id": "clip_1", "action": "x", "start_time": 0.0})
        dlg.clip_thumbnail_label.setText("Loading...")
        stale_id = dlg._frame_request_id - 1
        dlg._on_frame_fetched(stale_id, b"whatever")
        self.assertEqual(dlg.clip_thumbnail_label.text(), "Loading...")

    def test_on_frame_fetched_none_data_shows_no_preview(self):
        dlg, _fetch_mock = self._dialog_on_clip({"id": "clip_1", "action": "x", "start_time": 0.0})
        dlg._on_frame_fetched(dlg._frame_request_id, None)
        self.assertEqual(dlg.clip_thumbnail_label.text(), "No preview")

    def test_on_frame_fetched_undecodable_bytes_shows_no_preview(self):
        dlg, _fetch_mock = self._dialog_on_clip({"id": "clip_1", "action": "x", "start_time": 0.0})
        dlg._on_frame_fetched(dlg._frame_request_id, b"not an image")
        self.assertEqual(dlg.clip_thumbnail_label.text(), "No preview")

    def test_switching_clips_invalidates_previous_request(self):
        client = _fake_source_profile_client(
            profiles=[{"id": "team_fort", "name": "Team Fort"}],
            profile_by_id={"team_fort": {"id": "team_fort", "subjects": [], "clips": [
                {"id": "clip_1", "action": "a", "start_time": 0.0},
                {"id": "clip_2", "action": "b", "start_time": 1.0},
            ]}},
        )
        with patch.object(scb.SceneCastBuilderDialog, "_fetch_clip_thumbnail"):
            dlg = scb.SceneCastBuilderDialog(fbtools_client=client, mode="source_profile")
            dlg.source_profile_combo.setCurrentIndex(dlg.source_profile_combo.findData("team_fort"))
            dlg.clip_combo.setCurrentIndex(dlg.clip_combo.findData("clip_1"))
            first_request_id = dlg._frame_request_id
            dlg.clip_combo.setCurrentIndex(dlg.clip_combo.findData("clip_2"))
            second_request_id = dlg._frame_request_id
        self.assertNotEqual(first_request_id, second_request_id)
        # The first request's result must now be dropped as stale.
        dlg.clip_thumbnail_label.setText("Loading...")
        dlg._on_frame_fetched(first_request_id, b"whatever")
        self.assertEqual(dlg.clip_thumbnail_label.text(), "Loading...")


if __name__ == "__main__":
    unittest.main()
