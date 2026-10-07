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
    QPushButton, QCheckBox, QRadioButton, QButtonGroup, QWidget, QPixmap,
    QObject, QThread, pyqtSignal,
)

from classes.logger import log

_THUMBNAIL_WIDTH = 160
_THUMBNAIL_HEIGHT = 90


class _ClipFrameFetchWorker(QObject):
    """Fetches one clip-segment thumbnail frame off the UI thread. Disposable: a new worker
    (and thread) is spun up per fetch rather than reused, since these happen at most once per
    Clip Segment selection -- not a hot path worth pooling."""

    finished = pyqtSignal(int, object)  # request_id, raw JPEG bytes (or None on failure)

    def __init__(self, fbtools_client, profile_id, timestamp, request_id):
        super().__init__()
        self._fbtools_client = fbtools_client
        self._profile_id = profile_id
        self._timestamp = timestamp
        self._request_id = request_id

    def run(self):
        # Visible at the default log level (INFO) on purpose: a "stuck on Loading forever"
        # report with NOTHING from this worker in the log -- not even the "started" line --
        # means run() itself never got dispatched (a threading issue), not a slow/failing
        # HTTP call. The old log.debug() on the exception path was invisible by default
        # (info.LOG_LEVEL_FILE/CONSOLE are both "INFO"), so a real failure here could have
        # been happening silently on every attempt with nothing to show for it.
        log.info(
            "SceneCastBuilderDialog: thumbnail fetch started (request_id=%s, profile=%s, t=%s)",
            self._request_id, self._profile_id, self._timestamp,
        )
        try:
            data = self._fbtools_client.get_source_profile_frame(
                self._profile_id, self._timestamp, width=_THUMBNAIL_WIDTH,
            )
        except Exception as ex:
            log.warning(
                "SceneCastBuilderDialog: thumbnail fetch failed (request_id=%s): %s",
                self._request_id, ex,
            )
            data = None
        else:
            log.info(
                "SceneCastBuilderDialog: thumbnail fetch finished (request_id=%s, bytes=%s)",
                self._request_id, len(data) if data else 0,
            )
        self.finished.emit(self._request_id, data)


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
    """slot_assignments: [{"subject_id", "bundle_id", "primary", "use_audio"}, ...] (already
    filtered to slots where a bundle was actually chosen; "use_audio" = include that bundle's own
    audio as a reference) -> the cast_entries_json string. Matches
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
        if assignment.get("use_audio"):
            entry["use_audio"] = True
        entries.append(entry)
    return json.dumps(entries)


def find_clip(profile, clip_id):
    """Return the clip dict matching `clip_id` within `profile` (a source profile dict from
    FBToolsClient.get_source_profile), or None. Shared by the thumbnail-fetch and action-text
    display, both of which need the same clip lookup ordered_clip_subjects() does internally."""
    if not isinstance(profile, dict) or not clip_id:
        return None
    return next(
        (c for c in profile.get("clips", []) if isinstance(c, dict) and c.get("id") == clip_id),
        None,
    )


def ordered_clip_subjects(profile, clip_id):
    """Return [(source_subject_id, label), ...] for the subjects actually present in
    `clip_id` within `profile` (a source profile dict from FBToolsClient.get_source_profile),
    in the clip's own list order. A clip's own `subjects` field is just a list of ids (see
    utils/source_profiles.py::_normalize_clip) -- labels come from cross-referencing the
    profile's own subject roster; falls back to the bare id if a subject entry is missing."""
    clip = find_clip(profile, clip_id)
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
        if assignment.get("use_audio"):
            entry["use_audio"] = True
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


def build_background_override_id(background_value):
    """background_value: _USE_COMPOSITION_DEFAULT (no override) / "none" / a background id ->
    the background_override_id string fbTools' SceneCastBuild expects (nodes/scene_casts.py).
    Source Profile mode's own mechanism -- NOT JSON (unlike build_overrides_json above, which
    is Composition mode's composition_overrides_json): empty means "use the clip's own
    background_id, falling back to the profile's default_background_id"; "none" means
    explicitly no background for this run."""
    if background_value is _USE_COMPOSITION_DEFAULT:
        return ""
    return str(background_value)


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
        background_override_id="",
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
        self._initial_background_override_id = str(background_override_id or "").strip()

        self._bundles = []
        self._backgrounds = []
        self._source_profiles = []
        self._loaded_composition = None
        self._loaded_source_profile = None
        self._slot_widgets = {}  # key -> {..., "bundle_combo", "primary_radio"}
        self._primary_group = QButtonGroup(self)
        self._primary_group.setExclusive(True)
        self._frame_request_id = 0
        self._last_processed_clip_id = None
        # (thread, worker) kept alive here only until each one's own finished signal removes
        # it -- see _fetch_clip_thumbnail for why this must never be a single-slot reference.
        self._frame_threads = []

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
        else:
            root.addLayout(self._build_source_background_form())

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

        preview_row = QWidget(self)
        preview_layout = QHBoxLayout(preview_row)
        preview_layout.setContentsMargins(0, 0, 0, 0)
        self.clip_thumbnail_label = QLabel()
        self.clip_thumbnail_label.setFixedSize(_THUMBNAIL_WIDTH, _THUMBNAIL_HEIGHT)
        self.clip_thumbnail_label.setAlignment(Qt.AlignCenter)
        self.clip_thumbnail_label.setStyleSheet("border: 1px solid palette(mid);")
        self.clip_action_label = QLabel()
        self.clip_action_label.setWordWrap(True)
        self.clip_action_label.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        preview_layout.addWidget(self.clip_thumbnail_label, 0)
        preview_layout.addWidget(self.clip_action_label, 1)
        top_form.addRow("Preview", preview_row)

        return top_form

    def _build_background_form(self):
        background_form = QFormLayout()
        self.background_combo = QComboBox()
        self.background_as_reference_check = QCheckBox("Use background as reference image")
        background_form.addRow("Background", self.background_combo)
        background_form.addRow("", self.background_as_reference_check)
        return background_form

    def _build_source_background_form(self):
        """Source Profile mode's own background override -- a single combo, no "as reference"
        checkbox (SourceProfileClipPrompt always shows the resolved background as a reference
        image when one is set; there's no toggle for it, unlike Composition mode)."""
        background_form = QFormLayout()
        self.source_background_combo = QComboBox()
        background_form.addRow("Background Override", self.source_background_combo)
        return background_form

    # ---- data loading ----

    def _load_data(self):
        self._bundles = self._safe_list("list_bundles")
        self._backgrounds = self._safe_list("list_backgrounds")

        if self.mode == "source_profile":
            self._source_profiles = self._safe_list("list_source_profiles")
            for profile in self._source_profiles:
                if not isinstance(profile, dict):
                    continue
                label = profile.get("name") or profile.get("id", "")
                self.source_profile_combo.addItem(str(label), profile.get("id", ""))

            self.source_background_combo.clear()
            self.source_background_combo.addItem("(use clip/profile default)", _USE_COMPOSITION_DEFAULT)
            self.source_background_combo.addItem("(none, this run)", "none")
            for background in self._backgrounds:
                if not isinstance(background, dict):
                    continue
                label = background.get("name") or background.get("id", "")
                self.source_background_combo.addItem(str(label), background.get("id", ""))
            self._select_initial_background_override()
            return

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

    def _select_initial_background_override(self):
        value = self._initial_background_override_id or _USE_COMPOSITION_DEFAULT
        index = self.source_background_combo.findData(value)
        self.source_background_combo.setCurrentIndex(index if index >= 0 else 0)

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

    def _make_audio_check(self, bundle_combo):
        """The per-slot "Audio" checkbox: include the chosen bundle's own audio (its voice
        sample) as a reference for this slot. It means nothing without a bundle, so it is only
        enabled -- and only stays checked -- while a bundle is chosen."""
        audio_check = QCheckBox("Audio")
        audio_check.setToolTip(
            "Include this bundle's own audio (its voice sample) as a reference.\n"
            "For a Source Profile clip, the clip segment must also allow dialogue."
        )

        def _sync(_index=0, combo=bundle_combo, check=audio_check):
            has_bundle = bool(str(combo.currentData() or "").strip())
            check.setEnabled(has_bundle)
            if not has_bundle:
                check.setChecked(False)

        bundle_combo.currentIndexChanged.connect(_sync)
        _sync()
        return audio_check

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
            audio_check = self._make_audio_check(bundle_combo)

            initial_entry = initial_by_subject.get(subject_id)
            if initial_entry:
                bundle_index = bundle_combo.findData(str(initial_entry.get("bundle_id", "")))
                if bundle_index >= 0:
                    bundle_combo.setCurrentIndex(bundle_index)
                primary_radio.setChecked(bool(initial_entry.get("primary")))
                audio_check.setChecked(bool(initial_entry.get("use_audio")))

            row = QWidget(self)
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(0, 0, 0, 0)
            row_layout.addWidget(bundle_combo, 1)
            row_layout.addWidget(audio_check, 0)
            row_layout.addWidget(primary_radio, 0)
            self.slots_form.addRow("Slot {}".format(slot_letter), row)

            self._slot_widgets[slot_letter] = {
                "subject_id": subject_id,
                "bundle_combo": bundle_combo,
                "primary_radio": primary_radio,
                "audio_check": audio_check,
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
        if profile_id and self._loaded_source_profile is not None \
                and str(self._loaded_source_profile.get("id", "")) == profile_id:
            return  # already loaded (e.g. the initial-selection direct call after the signal
            # fired) -- mirrors _on_composition_changed's own early-return guard. Unlike that
            # one, this used to keep calling _rebuild_clip_combo() unconditionally even when
            # already_loaded was true, which rebuilds the clip combo (clip_combo.clear() +
            # re-populate) a second time -- clearing a combo with a selection emits its own
            # currentIndexChanged(-1), which reset _on_clip_changed's own dedup state (see its
            # comment) in between the two outer calls, letting a second real thumbnail fetch
            # through despite that guard. Returning early here, before any of that, is what
            # actually gets the fetch count down to one.
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
        clip_id = str(self.clip_combo.currentData() or "").strip()
        if clip_id and clip_id == self._last_processed_clip_id:
            return  # already processed (e.g. the initial-selection direct call after the signal fired) --
            # see _on_composition_changed's own matching guard. Without this, _select_initial_clip()
            # fires this twice for every initial clip_id (once via the signal, once via its own direct
            # call), each one unconditionally starting a NEW thumbnail-fetch thread (_update_clip_preview
            # below) -- two network requests for one visible selection, and -- since fixing the SIGABRT
            # crash below required no longer parenting that thread to this dialog -- the first (now
            # orphaned) thread got destroyed via plain Python refcounting the instant the second call
            # overwrote the single-slot thread reference, while possibly still mid-startup. That's an
            # unsafe QThread teardown in its own right and is what caused the later "stuck on Loading
            # forever" regression: not a slow network, a corrupted thread before it ever ran.
        self._last_processed_clip_id = clip_id
        self._update_clip_preview()
        self._rebuild_slot_rows()

    def _update_clip_preview(self):
        """Refresh the action-text label synchronously (already loaded, no I/O) and kick off
        an async thumbnail fetch for the newly-selected clip's first frame."""
        clip_id = str(self.clip_combo.currentData() or "").strip()
        clip = find_clip(self._loaded_source_profile, clip_id)

        self.clip_action_label.setText(str((clip or {}).get("action", "")).strip() or "(no action text)")

        # Invalidate any in-flight fetch for a previously-selected clip before starting a new
        # one -- _on_frame_fetched() drops results whose request_id no longer matches this.
        self._frame_request_id += 1
        if not clip or self.fbtools_client is None:
            self.clip_thumbnail_label.clear()
            self.clip_thumbnail_label.setText("No preview")
            return

        profile_id = str(self.source_profile_combo.currentData() or "").strip()
        start_time = float(clip.get("start_time", 0.0))
        self.clip_thumbnail_label.clear()
        self.clip_thumbnail_label.setText("Loading...")
        self._fetch_clip_thumbnail(profile_id, start_time, self._frame_request_id)

    def _fetch_clip_thumbnail(self, profile_id, timestamp, request_id):
        # Deliberately NOT parented to self (QThread(self)): this is a modal dialog that
        # can be closed -- and torn down, possibly cascading from an ancestor dialog's own
        # close -- before a slow fbTools response arrives (observed in practice when the
        # ComfyUI queue is busy). Qt's child-destruction cascade cannot safely destroy a
        # still-running QThread and hard-aborts ("QThread: Destroyed while thread is still
        # running", SIGABRT) if one is still a child when its parent widget is deleted.
        # Left unparented, the thread survives independently of this dialog's lifetime and
        # cleans itself up via its own finished -> quit/deleteLater chain regardless --
        # worst case it's an orphaned background thread for up to the fbtools_client call's
        # own timeout (15s in FBToolsClient._get_bytes). A stale result arriving after this
        # dialog is gone is already handled: PyQt auto-disconnects a signal from a deleted
        # QObject's slot, and _on_frame_fetched's own request_id check discards anything
        # superseded by a later clip selection even if this dialog is still alive.
        thread = QThread()
        worker = _ClipFrameFetchWorker(self.fbtools_client, profile_id, timestamp, request_id)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(self._on_frame_fetched)
        # Direct, not the default queued cross-thread connection: `thread` belongs to the
        # main thread, so a queued quit() would sit in the main event loop's queue until it's
        # next pumped -- which may never happen before this dialog (or the whole process, in
        # a headless unittest run) is torn down, leaving the background thread's own exec()
        # loop still running and orphaned. A direct connection has the worker's own thread
        # tell its event loop to quit immediately, with no dependency on the main loop at all.
        worker.finished.connect(thread.quit, Qt.DirectConnection)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(lambda t=thread: self._forget_frame_thread(t))
        # Track the (thread, worker) PAIR, never just the thread: worker is a local variable
        # here with no other Python reference and no parent, so the instant this method
        # returns -- which happens immediately after thread.start(), well before the OS has
        # actually scheduled the new thread to run -- CPython's refcounting destroys it on
        # the spot unless something else keeps it alive. That silently prevents
        # thread.started from ever actually invoking worker.run() at all: no exception, no
        # log output, nothing -- just a thumbnail stuck on "Loading..." forever. This was the
        # actual cause of the hang that unparenting the thread (see the comment above) did
        # NOT fix; tracking the thread alone was never enough.
        self._frame_threads.append((thread, worker))
        thread.start()

    def _forget_frame_thread(self, thread):
        self._frame_threads = [pair for pair in self._frame_threads if pair[0] is not thread]

    def _on_frame_fetched(self, request_id, data):
        if request_id != self._frame_request_id:
            log.info(
                "SceneCastBuilderDialog: discarding stale thumbnail result (request_id=%s, current=%s)",
                request_id, self._frame_request_id,
            )
            return  # superseded by a later Clip Segment selection -- drop this stale result
        if not data:
            log.info("SceneCastBuilderDialog: thumbnail result empty (request_id=%s) -> No preview", request_id)
            self.clip_thumbnail_label.setText("No preview")
            return
        pixmap = QPixmap()
        if pixmap.loadFromData(data):
            self.clip_thumbnail_label.setPixmap(
                pixmap.scaled(
                    _THUMBNAIL_WIDTH, _THUMBNAIL_HEIGHT, Qt.KeepAspectRatio, Qt.SmoothTransformation,
                )
            )
        else:
            self.clip_thumbnail_label.setText("No preview")

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
            audio_check = self._make_audio_check(bundle_combo)

            initial_entry = initial_by_source_subject.get(source_subject_id)
            if initial_entry:
                bundle_index = bundle_combo.findData(str(initial_entry.get("bundle_id", "")))
                if bundle_index >= 0:
                    bundle_combo.setCurrentIndex(bundle_index)
                primary_radio.setChecked(bool(initial_entry.get("primary")))
                audio_check.setChecked(bool(initial_entry.get("use_audio")))

            row = QWidget(self)
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(0, 0, 0, 0)
            row_layout.addWidget(bundle_combo, 1)
            row_layout.addWidget(audio_check, 0)
            row_layout.addWidget(primary_radio, 0)
            self.slots_form.addRow(label, row)

            self._slot_widgets[source_subject_id] = {
                "source_subject_id": source_subject_id,
                "bundle_combo": bundle_combo,
                "primary_radio": primary_radio,
                "audio_check": audio_check,
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
                "use_audio": slot["audio_check"].isChecked(),
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
                "use_audio": slot["audio_check"].isChecked(),
            })
        return build_source_profile_cast_entries_json(assignments)

    def composition_overrides_json(self):
        if self.mode == "source_profile":
            return "{}"
        return build_overrides_json(
            self.background_combo.currentData(),
            self.background_as_reference_check.isChecked(),
        )

    def background_override_id(self):
        if self.mode != "source_profile":
            return ""
        return build_background_override_id(self.source_background_combo.currentData())
