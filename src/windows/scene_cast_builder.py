"""
 @file
 @brief This file contains the Scene Cast builder dialog, used by GenerateMediaDialog's
        grouped "Scene Cast" widget to assign fbTools Subjects/Bundles/backgrounds to a
        Composition's slots for a from-scratch AI generation.
 @author Jonathan Thomas <jonathan@openshot.org>

 @section LICENSE

 Copyright (c) 2008-2026 OpenShot Studios, LLC
 (http://www.openshotstudios.com). This file is part of
 OpenShot Video Editor (http://www.openshot.org), an open-source project
 dedicated to delivering high quality video editing and animation solutions
 to the world.

 OpenShot Video Editor is free software: you can redistribute it and/or modify
 it under the terms of the GNU General Public License as published by
 the Free Software Foundation, either version 3 of the License, or
 (at your option) any later version.

 OpenShot Video Editor is distributed in the hope that it will be useful,
 but WITHOUT ANY WARRANTY; without even the implied warranty of
 MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
 GNU General Public License for more details.

 You should have received a copy of the GNU General Public License
 along with OpenShot Library.  If not, see <http://www.gnu.org/licenses/>.
"""

import json

from qt_api import (
    Qt, QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QLabel, QComboBox,
    QPushButton, QCheckBox, QRadioButton, QButtonGroup, QWidget,
)

from classes.logger import log

# Sentinel QComboBox userData for "leave this slot/background exactly as the Composition
# itself defines it" -- distinct from "" (bundle combo's own "no bundle chosen" state) and from
# the literal string "none" (composition_overrides_json's own "explicitly no background" value).
_USE_COMPOSITION_DEFAULT = None


def ordered_assigned_slots(composition):
    """Return [(slot_letter, subject_id), ...] from a composition's own `subjects` dict, in
    insertion order (never sorted -- slot_letter()'s A..Z, AA.. scheme sorts wrong as plain
    strings past Z, the same ordering bug fbTools' own generation_metadata.py guards against),
    skipping slots the Composition itself left unassigned (nothing there to override)."""
    if not isinstance(composition, dict):
        return []
    subjects = composition.get("subjects")
    if not isinstance(subjects, dict):
        return []
    return [(slot, str(subject_id)) for slot, subject_id in subjects.items() if subject_id]


def sort_bundles_for_subject(bundles, subject_id):
    """Bundles belonging to `subject_id` first (in their own given order), then every other
    bundle sorted by display name -- so a slot's combo surfaces its own subject's bundles
    without hiding the rest (a user may deliberately want a different subject's bundle here)."""
    if not isinstance(bundles, list):
        return []
    own = [b for b in bundles if isinstance(b, dict) and str(b.get("subject_id", "")) == subject_id]
    other = [b for b in bundles if not (isinstance(b, dict) and str(b.get("subject_id", "")) == subject_id)]
    other.sort(key=lambda b: str(b.get("name") or b.get("id", "")).lower())
    return own + other


def parse_cast_entries_json(text):
    """Best-effort parse of a cast_entries_json string back into a list of entry dicts."""
    try:
        parsed = json.loads(text or "[]")
    except Exception:
        return []
    return parsed if isinstance(parsed, list) else []


def parse_overrides_json(text):
    """Best-effort parse of a composition_overrides_json string back into a dict."""
    try:
        parsed = json.loads(text or "{}")
    except Exception:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def build_cast_entries_json(slot_assignments):
    """slot_assignments: [{"subject_id", "bundle_id", "primary"}, ...] (already filtered to
    slots where a bundle was actually chosen) -> the cast_entries_json string. Matches
    fbTools' SceneCastBuild bundle-only entry shape exactly (nodes/scene_casts.py::execute)."""
    entries = []
    for assignment in slot_assignments:
        subject_id = str(assignment.get("subject_id", "")).strip()
        bundle_id = str(assignment.get("bundle_id", "")).strip()
        if not subject_id or not bundle_id:
            continue
        entry = {"subject_id": subject_id, "bundle_id": bundle_id}
        if assignment.get("primary"):
            entry["primary"] = True
        entries.append(entry)
    return json.dumps(entries)


def ordered_clip_subjects(profile, clip_id):
    """Return [(source_subject_id, label), ...] for the subjects actually present in
    `clip_id` within `profile` (a source profile dict from FBToolsClient.get_source_profile),
    in the clip's own list order. A clip's own `subjects` field is just a list of ids (see
    utils/source_profiles.py::_normalize_clip) -- labels come from cross-referencing the
    profile's own subject roster; falls back to the bare id if a subject entry is missing."""
    if not isinstance(profile, dict) or not clip_id:
        return []
    clip = next(
        (c for c in profile.get("clips", []) if isinstance(c, dict) and c.get("id") == clip_id),
        None,
    )
    if not clip:
        return []
    labels_by_id = {
        str(s.get("id", "")): str(s.get("label") or s.get("id", ""))
        for s in profile.get("subjects", []) if isinstance(s, dict)
    }
    return [
        (subject_id, labels_by_id.get(subject_id, subject_id))
        for subject_id in (clip.get("subjects") or []) if subject_id
    ]


def build_source_profile_cast_entries_json(slot_assignments):
    """slot_assignments: [{"subject_id" (the replacement bundle's own subject),
    "bundle_id", "source_profile_id", "source_subject_id" (who in the footage this
    replaces), "primary"}, ...] (already filtered to rows where a bundle was actually
    chosen) -> the cast_entries_json string. Matches fbTools' SceneCastBuild hybrid
    (source + bundle) entry shape (nodes/scene_casts.py::execute)."""
    entries = []
    for assignment in slot_assignments:
        subject_id = str(assignment.get("subject_id", "")).strip()
        bundle_id = str(assignment.get("bundle_id", "")).strip()
        source_profile_id = str(assignment.get("source_profile_id", "")).strip()
        source_subject_id = str(assignment.get("source_subject_id", "")).strip()
        if not subject_id or not bundle_id or not source_profile_id or not source_subject_id:
            continue
        entry = {
            "subject_id": subject_id,
            "bundle_id": bundle_id,
            "source_profile_id": source_profile_id,
            "source_subject_id": source_subject_id,
        }
        if assignment.get("primary"):
            entry["primary"] = True
        entries.append(entry)
    return json.dumps(entries)


def build_overrides_json(background_value, background_as_reference):
    """background_value: _USE_COMPOSITION_DEFAULT (omit the key entirely) / "none" / a
    background id. background_as_reference: only ever written when True -- leaving it unchecked
    means "use whatever the Composition itself says", matching apply_composition_overrides'
    own "present only when it differs" contract (utils/prompt_compositions.py)."""
    overrides = {}
    if background_value is not _USE_COMPOSITION_DEFAULT:
        overrides["background"] = background_value
    if background_as_reference:
        overrides["background_as_reference"] = True
    return json.dumps(overrides)


class SceneCastBuilderDialog(QDialog):
    """Modal "assign a Subject/Bundle per slot" builder -- the OpenShot-side analogue of
    fbTools' own Scene Cast Build ComfyUI node. Lists live data from fbTools' REST API via
    `fbtools_client` (an FBToolsClient, or None if unreachable -- every list call degrades to
    an empty combo rather than failing to open).

    Two modes, picked at construction time via `mode`:
      "composition"     -- pick a Composition, assign a Bundle (+ background override) to each
                            of its own slots. v1 only builds bundle-only cast entries
                            (subject_id + bundle_id [+ primary]).
      "source_profile"  -- pick a Source Profile + one Clip Segment within it, optionally
                            replace any of that clip's own subjects with a Bundle (hybrid
                            source + bundle entries: subject_id + bundle_id + source_profile_id
                            + source_subject_id [+ primary]). No ordinal/pronoun-pool matching
                            in this mode -- every row is an explicit, single clip's subject.
    """

    def __init__(
        self,
        fbtools_client=None,
        mode="composition",
        composition_name="",
        cast_entries_json="[]",
        composition_overrides_json="{}",
        source_profile_id="",
        clip_id="",
        parent=None,
    ):
        super().__init__(parent)
        self.fbtools_client = fbtools_client
        self.mode = mode if mode in ("composition", "source_profile") else "composition"
        self._initial_composition_name = str(composition_name or "").strip()
        self._initial_entries = parse_cast_entries_json(cast_entries_json)
        self._initial_overrides = parse_overrides_json(composition_overrides_json)
        self._initial_source_profile_id = str(source_profile_id or "").strip()
        self._initial_clip_id = str(clip_id or "").strip()

        self._bundles = []
        self._backgrounds = []
        self._source_profiles = []
        self._loaded_composition = None
        self._loaded_source_profile = None
        self._slot_widgets = {}  # key -> {..., "bundle_combo", "primary_radio"}
        self._primary_group = QButtonGroup(self)
        self._primary_group.setExclusive(True)

        self.setObjectName("sceneCastBuilderDialog")
        self.setWindowTitle("Edit Scene Cast")
        self.setMinimumWidth(520)
        self.setMinimumHeight(420)

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 14, 14, 14)
        root.setSpacing(10)

        if self.mode == "source_profile":
            root.addLayout(self._build_source_profile_top_form())
        else:
            root.addLayout(self._build_composition_top_form())

        self.slots_container = QWidget(self)
        self.slots_form = QFormLayout(self.slots_container)
        self.slots_form.setContentsMargins(0, 0, 0, 0)
        root.addWidget(self.slots_container, 1)

        if self.mode == "composition":
            root.addLayout(self._build_background_form())

        button_row = QHBoxLayout()
        button_row.addStretch(1)
        cancel_button = QPushButton("Cancel")
        ok_button = QPushButton("OK")
        cancel_button.clicked.connect(self.reject)
        ok_button.clicked.connect(self.accept)
        button_row.addWidget(cancel_button)
        button_row.addWidget(ok_button)
        root.addLayout(button_row)

        self._load_data()
        if self.mode == "source_profile":
            self._select_initial_source_profile()
        else:
            self._select_initial_composition()

    # ---- widget construction ----

    def _build_composition_top_form(self):
        top_form = QFormLayout()
        self.composition_combo = QComboBox()
        self.composition_combo.addItem("Choose a composition...", "")
        self.composition_combo.currentIndexChanged.connect(self._on_composition_changed)
        top_form.addRow("Composition", self.composition_combo)
        return top_form

    def _build_source_profile_top_form(self):
        top_form = QFormLayout()
        self.source_profile_combo = QComboBox()
        self.source_profile_combo.addItem("Choose a source profile...", "")
        self.source_profile_combo.currentIndexChanged.connect(self._on_source_profile_changed)
        self.clip_combo = QComboBox()
        self.clip_combo.addItem("Choose a clip segment...", "")
        self.clip_combo.currentIndexChanged.connect(self._on_clip_changed)
        top_form.addRow("Source Profile", self.source_profile_combo)
        top_form.addRow("Clip Segment", self.clip_combo)
        return top_form

    def _build_background_form(self):
        background_form = QFormLayout()
        self.background_combo = QComboBox()
        self.background_as_reference_check = QCheckBox("Use background as reference image")
        background_form.addRow("Background", self.background_combo)
        background_form.addRow("", self.background_as_reference_check)
        return background_form

    # ---- data loading ----

    def _load_data(self):
        self._bundles = self._safe_list("list_bundles")

        if self.mode == "source_profile":
            self._source_profiles = self._safe_list("list_source_profiles")
            for profile in self._source_profiles:
                if not isinstance(profile, dict):
                    continue
                label = profile.get("name") or profile.get("id", "")
                self.source_profile_combo.addItem(str(label), profile.get("id", ""))
            return

        self._backgrounds = self._safe_list("list_backgrounds")
        self.background_combo.clear()
        self.background_combo.addItem("(use Composition default)", _USE_COMPOSITION_DEFAULT)
        self.background_combo.addItem("(none)", "none")
        for background in self._backgrounds:
            if not isinstance(background, dict):
                continue
            label = background.get("name") or background.get("id", "")
            self.background_combo.addItem(str(label), background.get("id", ""))

        compositions = self._safe_list("list_compositions")
        for composition in compositions:
            if not isinstance(composition, dict):
                continue
            label = composition.get("name") or composition.get("id", "")
            self.composition_combo.addItem(str(label), composition.get("id", ""))

    def _safe_list(self, method_name):
        if self.fbtools_client is None:
            return []
        try:
            return getattr(self.fbtools_client, method_name)() or []
        except Exception as ex:
            log.warning("SceneCastBuilderDialog: %s failed: %s", method_name, ex)
            return []

    def _select_initial_composition(self):
        if not self._initial_composition_name:
            return
        index = self.composition_combo.findData(self._initial_composition_name)
        if index >= 0:
            self.composition_combo.setCurrentIndex(index)
        # setCurrentIndex() only emits currentIndexChanged when the index actually changes, so a
        # match on the already-current index (or no match at all) would otherwise never load the
        # slot rows. _on_composition_changed is idempotent against repeat calls -- call it
        # directly to guarantee it has run at least once.
        self._on_composition_changed(self.composition_combo.currentIndex())

    def _select_initial_source_profile(self):
        if not self._initial_source_profile_id:
            return
        index = self.source_profile_combo.findData(self._initial_source_profile_id)
        if index >= 0:
            self.source_profile_combo.setCurrentIndex(index)
        self._on_source_profile_changed(self.source_profile_combo.currentIndex())

    def _select_initial_clip(self):
        if not self._initial_clip_id:
            return
        index = self.clip_combo.findData(self._initial_clip_id)
        if index >= 0:
            self.clip_combo.setCurrentIndex(index)
        self._on_clip_changed(self.clip_combo.currentIndex())

    # ---- composition mode: slot rebuilding ----

    def _on_composition_changed(self, index):
        _ = index
        composition_id = str(self.composition_combo.currentData() or "").strip()
        if composition_id and self._loaded_composition is not None \
                and str(self._loaded_composition.get("id", "")) == composition_id:
            return  # already loaded (e.g. the initial-selection direct call after the signal fired)
        self._loaded_composition = None
        if composition_id and self.fbtools_client is not None:
            try:
                self._loaded_composition = self.fbtools_client.get_composition(composition_id)
            except Exception as ex:
                log.warning("SceneCastBuilderDialog: get_composition(%s) failed: %s", composition_id, ex)
        self._rebuild_slot_rows()

    def _rebuild_slot_rows(self):
        while self.slots_form.rowCount():
            self.slots_form.removeRow(0)
        self._slot_widgets = {}
        for button in list(self._primary_group.buttons()):
            self._primary_group.removeButton(button)

        if self.mode == "source_profile":
            self._rebuild_source_profile_slot_rows()
        else:
            self._rebuild_composition_slot_rows()

    def _rebuild_composition_slot_rows(self):
        initial_by_subject = {
            str(entry.get("subject_id", "")): entry
            for entry in self._initial_entries if isinstance(entry, dict)
        }

        for slot_letter, subject_id in ordered_assigned_slots(self._loaded_composition):
            bundle_combo = QComboBox()
            bundle_combo.addItem("(use Composition default)", "")
            for bundle in sort_bundles_for_subject(self._bundles, subject_id):
                label = bundle.get("name") or bundle.get("id", "")
                bundle_combo.addItem(str(label), bundle.get("id", ""))

            primary_radio = QRadioButton("Primary")
            self._primary_group.addButton(primary_radio)

            initial_entry = initial_by_subject.get(subject_id)
            if initial_entry:
                bundle_index = bundle_combo.findData(str(initial_entry.get("bundle_id", "")))
                if bundle_index >= 0:
                    bundle_combo.setCurrentIndex(bundle_index)
                primary_radio.setChecked(bool(initial_entry.get("primary")))

            row = QWidget(self)
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(0, 0, 0, 0)
            row_layout.addWidget(bundle_combo, 1)
            row_layout.addWidget(primary_radio, 0)
            self.slots_form.addRow("Slot {}".format(slot_letter), row)

            self._slot_widgets[slot_letter] = {
                "subject_id": subject_id,
                "bundle_combo": bundle_combo,
                "primary_radio": primary_radio,
            }

        self._apply_initial_overrides_once()

    def _apply_initial_overrides_once(self):
        """Pre-select the Background combo/checkbox from the dialog's initial
        composition_overrides_json -- safe to re-run on every slot rebuild since it only reads
        from the dialog's own immutable initial state, never from live widget values."""
        background_value = self._initial_overrides.get("background", _USE_COMPOSITION_DEFAULT)
        index = self.background_combo.findData(background_value)
        self.background_combo.setCurrentIndex(index if index >= 0 else 0)
        self.background_as_reference_check.setChecked(
            bool(self._initial_overrides.get("background_as_reference", False))
        )

    # ---- source profile mode: clip/slot rebuilding ----

    def _on_source_profile_changed(self, index):
        _ = index
        profile_id = str(self.source_profile_combo.currentData() or "").strip()
        already_loaded = (
            profile_id and self._loaded_source_profile is not None
            and str(self._loaded_source_profile.get("id", "")) == profile_id
        )
        if not already_loaded:
            self._loaded_source_profile = None
            if profile_id and self.fbtools_client is not None:
                try:
                    self._loaded_source_profile = self.fbtools_client.get_source_profile(profile_id)
                except Exception as ex:
                    log.warning("SceneCastBuilderDialog: get_source_profile(%s) failed: %s", profile_id, ex)
        self._rebuild_clip_combo()

    def _rebuild_clip_combo(self):
        self.clip_combo.clear()
        self.clip_combo.addItem("Choose a clip segment...", "")
        clips = (self._loaded_source_profile or {}).get("clips", []) \
            if isinstance(self._loaded_source_profile, dict) else []
        for clip in clips:
            if not isinstance(clip, dict):
                continue
            label = clip.get("label") or clip.get("id", "")
            self.clip_combo.addItem(str(label), clip.get("id", ""))
        self._select_initial_clip()

    def _on_clip_changed(self, index):
        _ = index
        self._rebuild_slot_rows()

    def _rebuild_source_profile_slot_rows(self):
        clip_id = str(self.clip_combo.currentData() or "").strip()
        initial_by_source_subject = {
            str(entry.get("source_subject_id", "")): entry
            for entry in self._initial_entries if isinstance(entry, dict)
        }

        for source_subject_id, label in ordered_clip_subjects(self._loaded_source_profile, clip_id):
            bundle_combo = QComboBox()
            bundle_combo.addItem("(keep original footage)", "")
            for bundle in sort_bundles_for_subject(self._bundles, source_subject_id):
                blabel = bundle.get("name") or bundle.get("id", "")
                bundle_combo.addItem(str(blabel), bundle.get("id", ""))

            primary_radio = QRadioButton("Primary")
            self._primary_group.addButton(primary_radio)

            initial_entry = initial_by_source_subject.get(source_subject_id)
            if initial_entry:
                bundle_index = bundle_combo.findData(str(initial_entry.get("bundle_id", "")))
                if bundle_index >= 0:
                    bundle_combo.setCurrentIndex(bundle_index)
                primary_radio.setChecked(bool(initial_entry.get("primary")))

            row = QWidget(self)
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(0, 0, 0, 0)
            row_layout.addWidget(bundle_combo, 1)
            row_layout.addWidget(primary_radio, 0)
            self.slots_form.addRow(label, row)

            self._slot_widgets[source_subject_id] = {
                "source_subject_id": source_subject_id,
                "bundle_combo": bundle_combo,
                "primary_radio": primary_radio,
            }

    # ---- result accessors (read after exec_() == QDialog.Accepted) ----

    def composition_name(self):
        if self.mode != "composition":
            return ""
        return str(self.composition_combo.currentData() or "").strip()

    def source_profile_id(self):
        if self.mode != "source_profile":
            return ""
        return str(self.source_profile_combo.currentData() or "").strip()

    def clip_id(self):
        if self.mode != "source_profile":
            return ""
        return str(self.clip_combo.currentData() or "").strip()

    def cast_entries_json(self):
        if self.mode == "source_profile":
            return self._source_profile_cast_entries_json()
        return self._composition_cast_entries_json()

    def _composition_cast_entries_json(self):
        assignments = []
        for slot in self._slot_widgets.values():
            bundle_id = str(slot["bundle_combo"].currentData() or "").strip()
            if not bundle_id:
                continue
            assignments.append({
                "subject_id": slot["subject_id"],
                "bundle_id": bundle_id,
                "primary": slot["primary_radio"].isChecked(),
            })
        return build_cast_entries_json(assignments)

    def _source_profile_cast_entries_json(self):
        profile_id = self.source_profile_id()
        assignments = []
        for slot in self._slot_widgets.values():
            bundle_id = str(slot["bundle_combo"].currentData() or "").strip()
            if not bundle_id:
                continue
            bundle = next(
                (b for b in self._bundles if isinstance(b, dict) and b.get("id") == bundle_id),
                None,
            )
            subject_id = str((bundle or {}).get("subject_id", "")).strip()
            assignments.append({
                "subject_id": subject_id,
                "bundle_id": bundle_id,
                "source_profile_id": profile_id,
                "source_subject_id": slot["source_subject_id"],
                "primary": slot["primary_radio"].isChecked(),
            })
        return build_source_profile_cast_entries_json(assignments)

    def composition_overrides_json(self):
        if self.mode == "source_profile":
            return "{}"
        return build_overrides_json(
            self.background_combo.currentData(),
            self.background_as_reference_check.isChecked(),
        )
