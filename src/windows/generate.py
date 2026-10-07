"""
 @file
 @brief This file contains the Generate media dialog.
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

import os
import json
import functools

from qt_api import Qt, QSize
from qt_api import QIcon, QPixmap, QColor
from qt_api import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QLabel, QLineEdit,
    QComboBox, QTextEdit, QTabWidget, QWidget, QPushButton, QMessageBox,
    QDoubleSpinBox, QSpinBox, QFileDialog
)

from classes import info
from classes.app import get_app
from classes.logger import log
from classes.thumbnail import GetThumbPath
from classes.query import File
from windows.region import SelectRegion
from windows.color_picker import ColorPicker
from windows.scene_cast_builder import SceneCastBuilderDialog

# Fallback values for a "scene_cast" grouped extra_inputs entry that doesn't declare its own
# "default" -- cast_entries_json/composition_overrides_json must always be valid JSON since the
# ComfyUI SceneCastBuild node parses them unconditionally.
_SCENE_CAST_KEY_DEFAULTS = {
    "composition_name": "",
    "cast_entries_json": "[]",
    "composition_overrides_json": "{}",
    "source_profile_id": "",
    "clip_id": "",
    "background_override_id": "",
}


class GenerateMediaDialog(QDialog):
    """Minimal generate dialog with a simple default-first layout."""

    PREVIEW_WIDTH = 180
    PREVIEW_HEIGHT = 128

    def __init__(
        self,
        source_file=None,
        templates=None,
        preselected_template_id=None,
        dialog_title=None,
        parent=None,
        default_name=None,
        fbtools_client=None,
        cast_metadata_resolver=None,
    ):
        super().__init__(parent)
        self.source_file = source_file
        self.templates = templates or []
        self.default_name = str(default_name or "").strip()
        self.template_map = {
            str(t.get("id", "")).strip(): (t.get("template") or {})
            for t in self.templates
        }
        self.preselected_template_id = str(preselected_template_id or "").strip()
        # fbtools_client: an FBToolsClient (or None) the Scene Cast builder dialog uses to list
        # Compositions/Bundles/Subjects/Backgrounds. cast_metadata_resolver: an optional zero-arg
        # callable returning a resolved cast-metadata dict (see classes/clip_cast_metadata.py) for
        # `source_file`, used to pre-fill the Scene Cast summary the first time a scene_cast-group
        # template is selected -- kept as an injected callable (rather than this dialog importing
        # clip_cast_metadata/fbtools_client itself) so this file stays free of I/O concerns.
        self.fbtools_client = fbtools_client
        self._cast_metadata_resolver = cast_metadata_resolver
        self._scene_cast_prefill_attempted = False
        self._scene_cast_entries = {}
        self._coordinates_positive_text = ""
        self._coordinates_negative_text = ""
        self._rectangles_positive_text = ""
        self._rectangles_negative_text = ""
        self._auto_mode = False
        self._tracking_selection_payload = {}
        self.setObjectName("generateDialog")
        self.setWindowTitle(str(dialog_title or "AI Tools"))
        self.setMinimumWidth(620)
        self.setMinimumHeight(460)

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 14, 14, 14)
        root.setSpacing(10)

        root.addLayout(self._build_top_block())

        self.tabs = QTabWidget(self)
        self.tabs.setObjectName("generateTabs")
        self.page_prompt = self._build_prompt_tab()
        self.page_reference = self._build_reference_tab()
        self.page_points = self._build_points_tab()
        self.page_highlight = self._build_highlight_tab()
        self.prompt_tab_index = self.tabs.addTab(self.page_prompt, "Prompt")
        self.reference_tab_index = self.tabs.addTab(self.page_reference, "Reference")
        self.points_tab_index = self.tabs.addTab(self.page_points, "Tracking")
        self.highlight_tab_index = self.tabs.addTab(self.page_highlight, "Highlight")
        root.addWidget(self.tabs, 1)

        button_row = QHBoxLayout()
        button_row.addStretch(1)
        self.cancel_button = QPushButton("Cancel")
        self.generate_button = QPushButton("Generate")
        self.generate_button.setIcon(QIcon(":/icons/Humanity/actions/16/star.svg"))
        self.cancel_button.clicked.connect(self.reject)
        self.generate_button.clicked.connect(self._on_generate_clicked)
        button_row.addWidget(self.cancel_button)
        button_row.addWidget(self.generate_button)
        root.addLayout(button_row)
        self._initialize_dialog_state()

    def _current_coordinates_text(self):
        coordinates_positive = str(self._coordinates_positive_text or "").strip()
        coordinates_negative = str(self._coordinates_negative_text or "").strip()
        rects_positive = str(self._rectangles_positive_text or "").strip()
        rects_negative = str(self._rectangles_negative_text or "").strip()
        auto_mode = bool(self._auto_mode)
        tracking_payload = dict(self._tracking_selection_payload or {})
        if not coordinates_positive and hasattr(self, "points_preview"):
            preview_text = self.points_preview.toPlainText().strip()
            if preview_text.startswith("{"):
                try:
                    payload = json.loads(preview_text.replace("'", "\""))
                    coordinates_positive = str(payload.get("positive", "")).strip() or coordinates_positive
                    coordinates_negative = str(payload.get("negative", "")).strip() or coordinates_negative
                    rects_positive = str(payload.get("positive_rects", "")).strip() or rects_positive
                    rects_negative = str(payload.get("negative_rects", "")).strip() or rects_negative
                    auto_mode = bool(payload.get("auto_mode", auto_mode))
                    if isinstance(payload.get("tracking_selection"), dict):
                        tracking_payload = payload.get("tracking_selection")
                except Exception:
                    pass
        prompt_text = self.prompt_edit.toPlainText().strip()
        return coordinates_positive, coordinates_negative, rects_positive, rects_negative, auto_mode, tracking_payload, prompt_text

    def get_payload(self):
        coordinates_positive, coordinates_negative, rects_positive, rects_negative, auto_mode, tracking_payload, prompt_text = self._current_coordinates_text()
        highlight_color = self.highlight_color.name(QColor.HexArgb) if hasattr(self, "highlight_color") else ""
        border_color = self.border_color.name(QColor.HexArgb) if hasattr(self, "border_color") else ""
        border_width = int(self.border_width_spin.value()) if hasattr(self, "border_width_spin") else 0
        highlight_opacity = float(self.highlight_opacity_spin.value()) if hasattr(self, "highlight_opacity_spin") else 0.0
        mask_brightness = float(self.mask_brightness_spin.value()) if hasattr(self, "mask_brightness_spin") else 1.0
        background_brightness = float(self.background_brightness_spin.value()) if hasattr(self, "background_brightness_spin") else 1.0
        input_file_ids, input_text_values = self._collect_extra_input_values()
        return {
            "name": self.name_edit.text().strip(),
            "template_id": self.template_combo.currentData() or self.template_combo.currentText(),
            "prompt": prompt_text,
            "input_file_ids": input_file_ids,
            "input_text_values": input_text_values,
            "reference_image_file_id": input_file_ids.get("reference_image", ""),
            "coordinates_positive": coordinates_positive,
            "coordinates_negative": coordinates_negative,
            "rectangles_positive": rects_positive,
            "rectangles_negative": rects_negative,
            "auto_mode": bool(auto_mode),
            "tracking_selection": tracking_payload,
            "highlight_color": highlight_color,
            "highlight_opacity": highlight_opacity,
            "border_color": border_color,
            "border_width": border_width,
            "mask_brightness": mask_brightness,
            "background_brightness": background_brightness,
        }

    def _build_top_block(self):
        block = QHBoxLayout()
        block.setSpacing(12)

        if self.source_file:
            self.thumbnail_label = QLabel()
            self.thumbnail_label.setFixedSize(self.PREVIEW_WIDTH, self.PREVIEW_HEIGHT)
            self.thumbnail_label.setAlignment(Qt.AlignCenter)
            self.thumbnail_label.setStyleSheet("border: 1px solid palette(mid);")
            self._load_thumbnail()
            block.addWidget(self.thumbnail_label, 0)

        setup_form = QFormLayout()
        setup_form.setContentsMargins(0, 0, 0, 0)
        setup_form.setVerticalSpacing(8)

        default_name = self.default_name or "generation"

        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("Output file name")
        self.name_edit.setText(default_name)
        setup_form.addRow("Name", self.name_edit)

        self.template_combo = QComboBox()
        if self.templates:
            for template in self.templates:
                self.template_combo.addItem(template.get("name", ""), template.get("id", ""))
        else:
            self.template_combo.addItem("Basic Text to Image", "txt2img-basic")
        if self.preselected_template_id:
            index = self.template_combo.findData(self.preselected_template_id)
            if index >= 0:
                self.template_combo.setCurrentIndex(index)
        self.template_combo.currentIndexChanged.connect(self._on_template_changed)
        setup_form.addRow("Template", self.template_combo)

        right_container = QWidget(self)
        right_container.setLayout(setup_form)
        block.addWidget(right_container, 1)
        return block

    def _build_reference_tab(self):
        tab = QWidget(self)
        tab.setObjectName("pageReference")
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(10)

        self._extra_input_widgets = {}  # key -> (widget, entry_dict)
        self._extra_input_form = QFormLayout()
        self._extra_input_form.setSpacing(8)
        layout.addLayout(self._extra_input_form)
        layout.addStretch(1)
        return tab

    def _clear_extra_input_widgets(self):
        while self._extra_input_form.rowCount():
            self._extra_input_form.removeRow(0)
        self._extra_input_widgets = {}

    def _rebuild_extra_inputs(self, extra_inputs):
        """Rebuild the Reference tab's widgets to match the current template's
        declared extra_inputs: one file combo per image/video/audio entry (same
        Project-Files-backed pattern the original single reference-image combo used),
        or a text field for a "text" entry.

        Entries sharing `"group": "scene_cast"` are a special case: rather than one
        QLineEdit per entry, they're rendered as a single summary row + "Edit Cast..."
        button backed by SceneCastBuilderDialog (see _build_scene_cast_widgets). A
        template without this hint, or an older build that doesn't recognize it, falls
        through to the plain per-entry "text" rendering below -- still works, just a
        plain JSON text field instead of the richer builder.
        """
        self._clear_extra_input_widgets()
        self._scene_cast_entries = {}
        scene_cast_entries = [e for e in extra_inputs if e.get("group") == "scene_cast"]
        remaining_entries = [e for e in extra_inputs if e.get("group") != "scene_cast"]
        if scene_cast_entries:
            self._build_scene_cast_widgets(scene_cast_entries)

        for entry in remaining_entries:
            key = entry.get("key", "")
            entry_type = entry.get("type", "")
            label = entry.get("label") or key
            if entry_type == "text":
                widget = QLineEdit()
                widget.setPlaceholderText(label)
                default_value = entry.get("default")
                if isinstance(default_value, str) and default_value:
                    widget.setText(default_value)
            elif entry_type == "choice":
                widget = QComboBox()
                choices = entry.get("choices", [])
                widget.addItems(choices)
                default_value = entry.get("default")
                if isinstance(default_value, str) and default_value in choices:
                    widget.setCurrentIndex(choices.index(default_value))
            elif entry_type == "bundle":
                widget = QComboBox()
                widget.addItem("(none)", "")
                self._populate_bundle_combo(widget)
                default_value = entry.get("default")
                if isinstance(default_value, str) and default_value:
                    index = widget.findData(default_value)
                    if index >= 0:
                        widget.setCurrentIndex(index)
            else:
                widget = QComboBox()
                widget.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
                widget.setIconSize(QSize(96, 96))
                widget.addItem("Choose {}...".format(label.lower()), "")
                self._populate_media_combo(widget, entry_type)
                chooser = QPushButton("Choose...")
                chooser.clicked.connect(
                    lambda _checked, combo=widget, entry_label=label, media_type=entry_type:
                    self._choose_media_from_project_files(combo, entry_label, media_type)
                )
                picker = QWidget(self)
                picker_layout = QHBoxLayout(picker)
                picker_layout.setContentsMargins(0, 0, 0, 0)
                picker_layout.setSpacing(6)
                picker_layout.addWidget(widget, 1)
                picker_layout.addWidget(chooser)
                self._extra_input_form.addRow(label, picker)
                self._extra_input_widgets[key] = (widget, entry)
                continue
            self._extra_input_form.addRow(label, widget)
            self._extra_input_widgets[key] = (widget, entry)

    def _build_scene_cast_widgets(self, entries):
        """Build the grouped Scene Cast widget: one hidden QLineEdit per declared key (so
        _collect_extra_input_values()/_first_missing_required_input() need no special-casing --
        each still looks exactly like an ordinary "text" extra_inputs entry) plus a single
        visible summary row with an "Edit Cast..." button that opens SceneCastBuilderDialog.
        """
        for entry in entries:
            key = entry.get("key", "")
            if not key:
                continue
            widget = QLineEdit()
            widget.setVisible(False)
            default_value = entry.get("default")
            if not (isinstance(default_value, str) and default_value):
                default_value = _SCENE_CAST_KEY_DEFAULTS.get(key, "")
            widget.setText(default_value)
            self._extra_input_widgets[key] = (widget, entry)
            self._scene_cast_entries[key] = widget

        row = QWidget(self)
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        self.scene_cast_summary_label = QLabel()
        self.scene_cast_summary_label.setWordWrap(True)
        self.scene_cast_edit_button = QPushButton("Edit Cast...")
        self.scene_cast_edit_button.clicked.connect(self._edit_scene_cast_clicked)
        row_layout.addWidget(self.scene_cast_summary_label, 1)
        row_layout.addWidget(self.scene_cast_edit_button, 0)
        label_text = entries[0].get("group_label") or "Scene Cast"
        self._extra_input_form.addRow(label_text, row)
        self._refresh_scene_cast_summary()
        self._maybe_prefill_scene_cast()

    def _scene_cast_mode(self):
        """Which SceneCastBuilderDialog mode this template's grouped entries declare --
        determined purely by which keys are present, so generate.py never needs a separate
        "mode" flag of its own to stay in sync with."""
        if "source_profile_id" in self._scene_cast_entries:
            return "source_profile"
        return "composition"

    def _resolve_source_profile_name(self, profile_id):
        """Translate an internally-selected source-profile ID to the display name expected by
        the fbTools workflow payload. The builder and the generated API contract use different
        semantics: the builder stores IDs, but SourceProfileLoad.profile_name is a name field."""
        profile_id = str(profile_id or "").strip()
        if not profile_id:
            return ""
        if self.fbtools_client is None:
            return profile_id

        try:
            profiles = self.fbtools_client.list_source_profiles() or []
        except Exception:
            profiles = []
        for profile in profiles:
            if isinstance(profile, dict) and str(profile.get("id") or "").strip() == profile_id:
                name = str(profile.get("name") or profile.get("id") or "").strip()
                if name:
                    return name

        try:
            profile = self.fbtools_client.get_source_profile(profile_id) or {}
        except Exception:
            return profile_id
        name = str(profile.get("name") or profile.get("id") or "").strip()
        return name or profile_id

    def _edit_scene_cast_clicked(self):
        mode = self._scene_cast_mode()
        cast_widget = self._scene_cast_entries.get("cast_entries_json")

        if mode == "source_profile":
            profile_widget = self._scene_cast_entries.get("source_profile_id")
            clip_widget = self._scene_cast_entries.get("clip_id")
            bg_override_widget = self._scene_cast_entries.get("background_override_id")
            dlg = SceneCastBuilderDialog(
                fbtools_client=self.fbtools_client,
                mode="source_profile",
                source_profile_id=profile_widget.text() if profile_widget else "",
                clip_id=clip_widget.text() if clip_widget else "",
                cast_entries_json=cast_widget.text() if cast_widget else "[]",
                background_override_id=bg_override_widget.text() if bg_override_widget else "",
                parent=self,
            )
        else:
            profile_widget = clip_widget = bg_override_widget = None
            composition_widget = self._scene_cast_entries.get("composition_name")
            overrides_widget = self._scene_cast_entries.get("composition_overrides_json")
            dlg = SceneCastBuilderDialog(
                fbtools_client=self.fbtools_client,
                mode="composition",
                composition_name=composition_widget.text() if composition_widget else "",
                cast_entries_json=cast_widget.text() if cast_widget else "[]",
                composition_overrides_json=overrides_widget.text() if overrides_widget else "{}",
                parent=self,
            )

        if dlg.exec_() != QDialog.Accepted:
            return

        if mode == "source_profile":
            if profile_widget is not None:
                # Store the ID, not the resolved name: this widget's text is also what
                # source_profile_id=... gets fed back into the next time "Edit Cast..." is
                # opened (above), and the combo there is matched by ID (findData), not name --
                # storing the name here would silently fail to re-select the profile/clip on
                # a second edit. Name resolution happens where it's actually needed instead:
                # _refresh_scene_cast_summary (display) and _collect_extra_input_values
                # (the ComfyUI payload, which needs SourceProfileLoad's profile_name).
                profile_widget.setText(dlg.source_profile_id())
            if clip_widget is not None:
                clip_widget.setText(dlg.clip_id())
            if bg_override_widget is not None:
                bg_override_widget.setText(dlg.background_override_id())
        else:
            if composition_widget is not None:
                composition_widget.setText(dlg.composition_name())
            if overrides_widget is not None:
                overrides_widget.setText(dlg.composition_overrides_json())
        if cast_widget is not None:
            cast_widget.setText(dlg.cast_entries_json())
        self._refresh_scene_cast_summary()

    def _refresh_scene_cast_summary(self):
        if not hasattr(self, "scene_cast_summary_label"):
            return
        mode = self._scene_cast_mode()
        cast_widget = self._scene_cast_entries.get("cast_entries_json")
        try:
            raw_entries = json.loads(cast_widget.text()) if cast_widget and cast_widget.text().strip() else []
        except Exception:
            raw_entries = []
        if not isinstance(raw_entries, list):
            raw_entries = []

        parts = []
        if mode == "source_profile":
            profile_widget = self._scene_cast_entries.get("source_profile_id")
            clip_widget = self._scene_cast_entries.get("clip_id")
            bg_override_widget = self._scene_cast_entries.get("background_override_id")
            profile_id = profile_widget.text().strip() if profile_widget else ""
            clip_id = clip_widget.text().strip() if clip_widget else ""
            bg_override = bg_override_widget.text().strip() if bg_override_widget else ""
            if profile_id:
                parts.append("Source Profile: {}".format(self._resolve_source_profile_name(profile_id) or profile_id))
            if clip_id:
                parts.append("Clip: {}".format(clip_id))
            if bg_override == "none":
                parts.append("Background: (none)")
            elif bg_override:
                parts.append("Background: {}".format(bg_override))
            for cast_entry in raw_entries:
                if not isinstance(cast_entry, dict):
                    continue
                marker = "★ " if cast_entry.get("primary") else ""
                audio_note = " (+audio)" if cast_entry.get("use_audio") else ""
                parts.append("{}{} → {}{}".format(
                    marker, cast_entry.get("source_subject_id", "?"), cast_entry.get("bundle_id", "?"), audio_note,
                ))
        else:
            composition_widget = self._scene_cast_entries.get("composition_name")
            composition_name = composition_widget.text().strip() if composition_widget else ""
            if composition_name:
                parts.append("Composition: {}".format(composition_name))
            for cast_entry in raw_entries:
                if not isinstance(cast_entry, dict):
                    continue
                marker = "★ " if cast_entry.get("primary") else ""
                audio_note = " (+audio)" if cast_entry.get("use_audio") else ""
                parts.append("{}{}: {}{}".format(
                    marker, cast_entry.get("subject_id", "?"), cast_entry.get("bundle_id", "?"), audio_note,
                ))
        self.scene_cast_summary_label.setText(" · ".join(parts) if parts else "No cast selected.")

    def _maybe_prefill_scene_cast(self):
        """Best-effort, one-time pre-fill of the Scene Cast widget from the selected source
        file's own embedded generation metadata (see classes/clip_cast_metadata.py) -- lets a
        user re-generate starting from the same Composition/Subject/Bundle an existing clip was
        built from, without retyping it. Runs at most once per dialog lifetime (not on every
        template switch) since both steps involve real I/O (a local ffprobe shell-out, then an
        HTTP call to fbTools). Any failure/absence leaves the widget exactly as it started --
        this is pure convenience, never a hard requirement for the dialog to work.

        Composition-mode only: the resolved metadata gives back a composition_name/primary
        subject+bundle, which has nothing to map onto a source_profile_id/clip_id pair, so
        source_profile-mode templates are left for the user to fill in by hand.
        """
        if self._scene_cast_mode() != "composition":
            return
        if self._scene_cast_prefill_attempted or not callable(self._cast_metadata_resolver):
            return
        self._scene_cast_prefill_attempted = True
        try:
            result = self._cast_metadata_resolver()
        except Exception as ex:
            log.debug("GenerateMediaDialog scene-cast pre-fill failed: %s", ex)
            return
        if not isinstance(result, dict):
            return

        composition_widget = self._scene_cast_entries.get("composition_name")
        cast_widget = self._scene_cast_entries.get("cast_entries_json")
        composition_name = str(result.get("composition_name") or "").strip()
        primary_subject = str(result.get("primary_subject") or "").strip()
        primary_bundle = str(result.get("primary_bundle") or "").strip()

        if composition_widget is not None and composition_name:
            composition_widget.setText(composition_name)
        if cast_widget is not None and primary_subject and primary_bundle:
            cast_widget.setText(json.dumps([
                {"subject_id": primary_subject, "bundle_id": primary_bundle, "primary": True},
            ]))
        self._refresh_scene_cast_summary()

    def _collect_extra_input_values(self):
        """Read the current Reference-tab widgets back into the two payload dicts
        Phase 3 expects: file ids for media inputs, raw strings for text inputs.
        """
        input_file_ids = {}
        input_text_values = {}
        for key, (widget, entry) in self._extra_input_widgets.items():
            if entry.get("type") == "text":
                value = widget.text().strip()
                if key == "source_profile_id":
                    # The widget stores fbTools' source-profile ID (see
                    # _edit_scene_cast_clicked), but SourceProfileLoad's own input is a name
                    # field -- resolve only here, at the point this becomes the actual
                    # ComfyUI payload, so the stored ID itself stays intact for re-editing.
                    value = self._resolve_source_profile_name(value) or value
                input_text_values[key] = value
            elif entry.get("type") == "choice":
                input_text_values[key] = widget.currentText().strip()
            elif entry.get("type") == "bundle":
                # Not a Project Files id -- an fbTools bundle id, substituted the same
                # way a plain "text" entry's literal value would be.
                input_text_values[key] = str(widget.currentData() or "").strip()
            else:
                input_file_ids[key] = str(widget.currentData() or "").strip()
        return input_file_ids, input_text_values

    def _build_prompt_tab(self):
        tab = QWidget(self)
        tab.setObjectName("pagePrompt")
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(8, 8, 8, 8)
        self.prompt_edit = QTextEdit()
        self.prompt_edit.setPlaceholderText("Prompt (optional)")
        self.prompt_edit.setMinimumHeight(140)
        layout.addWidget(self.prompt_edit)
        return tab

    def _build_points_tab(self):
        tab = QWidget(self)
        tab.setObjectName("pagePoints")
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(8, 8, 8, 8)
        controls = QHBoxLayout()
        self.pick_points_button = QPushButton("Select objects for tracking")
        self.clear_points_button = QPushButton("Clear")
        self.pick_points_button.clicked.connect(self._choose_tracking_clicked)
        self.clear_points_button.clicked.connect(self._clear_points_clicked)
        controls.addWidget(self.pick_points_button)
        controls.addWidget(self.clear_points_button)
        controls.addStretch(1)
        layout.addLayout(controls)

        self.points_preview = QTextEdit()
        self.points_preview.setReadOnly(True)
        self.points_preview.setMinimumHeight(90)
        layout.addWidget(self.points_preview)
        layout.addStretch(1)
        return tab

    def _build_highlight_tab(self):
        tab = QWidget(self)
        tab.setObjectName("pageHighlight")
        layout = QFormLayout(tab)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setVerticalSpacing(8)
        self.highlight_color = QColor("#2EA6FF")
        self.highlight_color.setAlphaF(0.70)
        self.border_color = QColor("#FFFFFF")
        self.border_color.setAlphaF(1.0)
        self.highlight_color_button = QPushButton("Choose Color")
        self.highlight_color_button.clicked.connect(self._pick_highlight_color)
        self.border_color_button = QPushButton("Choose Color")
        self.border_color_button.clicked.connect(self._pick_border_color)
        self.highlight_opacity_spin = QDoubleSpinBox()
        self.highlight_opacity_spin.setRange(0.0, 1.0)
        self.highlight_opacity_spin.setSingleStep(0.05)
        self.highlight_opacity_spin.setValue(0.28)
        self.border_width_spin = QSpinBox()
        self.border_width_spin.setRange(0, 64)
        self.border_width_spin.setValue(2)
        self.mask_brightness_spin = QDoubleSpinBox()
        self.mask_brightness_spin.setRange(0.0, 3.0)
        self.mask_brightness_spin.setSingleStep(0.05)
        self.mask_brightness_spin.setValue(1.15)
        self.background_brightness_spin = QDoubleSpinBox()
        self.background_brightness_spin.setRange(0.0, 3.0)
        self.background_brightness_spin.setSingleStep(0.05)
        self.background_brightness_spin.setValue(0.75)
        layout.addRow("Background Color", self.highlight_color_button)
        layout.addRow("Background Opacity", self.highlight_opacity_spin)
        layout.addRow("Border Color", self.border_color_button)
        layout.addRow("Border Width", self.border_width_spin)
        layout.addRow("Mask Brightness", self.mask_brightness_spin)
        layout.addRow("Background Brightness", self.background_brightness_spin)
        self._update_highlight_color_button()
        self._update_border_color_button()
        return tab

    @staticmethod
    def _best_contrast(bg):
        colrgb = bg.getRgbF()
        lum = (0.299 * colrgb[0] + 0.587 * colrgb[1] + 0.114 * colrgb[2])
        return QColor(Qt.white) if lum < 0.5 else QColor(Qt.black)

    def _color_callback(self, setter_fn, refresh_fn, color):
        if not color or not color.isValid():
            return
        setter_fn(color)
        refresh_fn()

    def _pick_highlight_color(self):
        callback = functools.partial(
            self._color_callback,
            self._set_highlight_color,
            self._update_highlight_color_button,
        )
        ColorPicker(
            self.highlight_color,
            parent=self,
            title="Select a Color",
            callback=callback,
        )

    def _pick_border_color(self):
        callback = functools.partial(
            self._color_callback,
            self._set_border_color,
            self._update_border_color_button,
        )
        ColorPicker(
            self.border_color,
            parent=self,
            title="Select a Color",
            callback=callback,
        )

    def _set_highlight_color(self, color):
        self.highlight_color = QColor(color)

    def _set_border_color(self, color):
        self.border_color = QColor(color)

    def _update_highlight_color_button(self):
        fg = self._best_contrast(self.highlight_color)
        self.highlight_color_button.setStyleSheet(
            "QPushButton{background-color:%s;color:%s;}" %
            (self.highlight_color.name(QColor.HexArgb), fg.name())
        )

    def _update_border_color_button(self):
        fg = self._best_contrast(self.border_color)
        self.border_color_button.setStyleSheet(
            "QPushButton{background-color:%s;color:%s;}" %
            (self.border_color.name(QColor.HexArgb), fg.name())
        )

    def _load_thumbnail(self):
        path = ""
        media_type = self.source_file.data.get("media_type")
        if media_type in ["video", "image"]:
            path = GetThumbPath(self.source_file.id, 1)
        elif media_type == "audio":
            path = os.path.join(info.PATH, "images", "AudioThumbnail.svg")

        pix = QPixmap(path) if path else QPixmap()
        if not pix.isNull():
            pix = pix.scaled(
                self.PREVIEW_WIDTH - 2,
                self.PREVIEW_HEIGHT - 2,
                Qt.KeepAspectRatio,
                Qt.SmoothTransformation,
            )
            self.thumbnail_label.setPixmap(pix)
        else:
            self.thumbnail_label.setText("No Preview")

    def _on_generate_clicked(self):
        if not self.name_edit.text().strip():
            self.name_edit.setFocus(Qt.TabFocusReason)
            return
        missing = self._first_missing_required_input()
        if missing is not None:
            widget, entry = missing
            if entry.get("group") == "scene_cast":
                # These widgets are hidden (see _build_scene_cast_widgets) -- focusing one
                # directly would show nothing, so point at the visible "Edit Cast..." button
                # instead, which is where every scene_cast-grouped value actually comes from.
                QMessageBox.warning(
                    self, "Missing Input",
                    "Use \"Edit Cast...\" to choose a Composition and assign the cast.",
                )
                self.tabs.setCurrentWidget(self.page_reference)
                if hasattr(self, "scene_cast_edit_button"):
                    self.scene_cast_edit_button.setFocus(Qt.TabFocusReason)
                return
            if entry.get("type") in ("text", "choice"):
                message = "Enter a value for \"{}\".".format(entry.get("label", entry["key"]))
            elif entry.get("type") == "bundle":
                message = "Choose a bundle for \"{}\".".format(entry.get("label", entry["key"]))
            else:
                self.tabs.setCurrentWidget(self.page_reference)
                self._choose_media_from_project_files(
                    widget,
                    entry.get("label", entry["key"]),
                    entry.get("type", "file"),
                )
                return
            QMessageBox.warning(self, "Missing Input", message)
            self.tabs.setCurrentWidget(self.page_reference)
            widget.setFocus(Qt.TabFocusReason)
            return
        if self._is_track_object_template():
            coordinates_positive, _coordinates_negative, rects_positive, _rects_negative, auto_mode, _tracking_payload, prompt_text = self._current_coordinates_text()
            if (not auto_mode) and (not coordinates_positive) and (not rects_positive) and (not str(prompt_text or "").strip()):
                QMessageBox.warning(
                    self,
                    "Missing Selection",
                    "No SAM2 seed was provided. Add tracking points/rectangles or enter a prompt.",
                )
                self.tabs.setCurrentWidget(self.page_points)
                return
        self.accept()

    def _is_track_object_template(self):
        template_id = str(self.template_combo.currentData() or "").strip().lower()
        return template_id in (
            "video-blur-anything-sam2",
            "video-mask-anything-sam2",
            "video-highlight-anything-sam2",
            "image-blur-anything-sam2",
            "image-mask-anything-sam2",
            "image-highlight-anything-sam2",
        )

    def _is_highlight_template(self):
        template_id = str(self.template_combo.currentData() or "").strip().lower()
        return template_id in ("video-highlight-anything-sam2", "image-highlight-anything-sam2")

    def _template_uses_generic_prompt(self):
        """Return whether the workflow consumes the dialog's generic Prompt field."""
        prompt_tokens = ("__openshot_prompt__", "{{openshot_prompt}}", "$openshot_prompt")

        def contains_prompt(value):
            if isinstance(value, str):
                return any(token in value for token in prompt_tokens)
            if isinstance(value, dict):
                return any(contains_prompt(item) for item in value.values())
            if isinstance(value, list):
                return any(contains_prompt(item) for item in value)
            return False

        return contains_prompt(self._current_template().get("workflow", {}))

    def _current_template(self):
        template_id = str(self.template_combo.currentData() or "").strip()
        return self.template_map.get(template_id, {})

    def _first_missing_required_input(self):
        """Return (widget, entry) for the first declared extra_inputs entry with no
        value, or None if every required input is satisfied. Mirrors the original
        single reference-image required-field check, generalized to N declared inputs.
        """
        for entry in self._current_template().get("extra_inputs", []):
            if not entry.get("required", True):
                continue
            widget_entry = self._extra_input_widgets.get(entry.get("key", ""))
            if widget_entry is None:
                continue
            widget, _ = widget_entry
            if entry.get("type") == "text":
                value = widget.text().strip()
            elif entry.get("type") == "choice":
                value = widget.currentText().strip()
            else:
                value = str(widget.currentData() or "").strip()
            if not value:
                return widget, entry
        return None

    def _on_template_changed(self, index):
        _ = index
        is_track_template = self._is_track_object_template()
        is_highlight_template = self._is_highlight_template()
        extra_inputs = self._current_template().get("extra_inputs", [])
        self._rebuild_extra_inputs(extra_inputs)
        default_prompt = self._current_template().get("default_prompt", "")
        if default_prompt and not self.prompt_edit.toPlainText().strip():
            self.prompt_edit.setPlainText(default_prompt)
        self._set_tab_visible(self.reference_tab_index, bool(extra_inputs))
        self._set_tab_visible(
            self.prompt_tab_index,
            is_track_template or self._template_uses_generic_prompt(),
        )
        self._set_tab_visible(self.points_tab_index, is_track_template)
        self._set_tab_visible(self.highlight_tab_index, is_track_template and is_highlight_template)
        self.pick_points_button.setEnabled(bool(self.source_file) and is_track_template)
        self.clear_points_button.setEnabled(is_track_template)
        if is_track_template:
            self.pick_points_button.setText("Select objects for tracking")
            self.tabs.setCurrentWidget(self.page_points)
        else:
            self._set_tab_visible(
                self.prompt_tab_index,
                self._template_uses_generic_prompt(),
            )
            self._set_tab_visible(self.points_tab_index, False)
            self._set_tab_visible(self.highlight_tab_index, False)
            # Default to the Reference tab (not an empty/hidden Prompt tab) when the Prompt
            # field is inert: a scene_cast-grouped template (the real creative direction lives
            # in the Composition; "Edit Cast..." is on the Reference tab), or any template that
            # declares extra inputs but whose workflow never consumes the generic Prompt.
            if self._scene_cast_entries or (extra_inputs and not self._template_uses_generic_prompt()):
                self.tabs.setCurrentWidget(self.page_reference)
            else:
                self.tabs.setCurrentWidget(self.page_prompt)

    def _populate_media_combo(self, combo, media_type):
        """Populate `combo` with every Project Files entry matching `media_type`
        ("image", "video", or "audio") — same File.filter()-backed pattern the
        original single-purpose reference-image combo used, generalized to any
        declared extra_inputs media type.
        """
        current_id = str(combo.currentData() or "").strip()
        media_files = []
        for file_obj in File.filter():
            data = file_obj.data if isinstance(getattr(file_obj, "data", None), dict) else {}
            if str(data.get("media_type", "")).strip().lower() != media_type:
                continue
            media_files.append(file_obj)

        media_files.sort(key=lambda f: str((f.data or {}).get("name") or os.path.basename((f.data or {}).get("path", ""))).lower())
        for file_obj in media_files:
            data = file_obj.data if isinstance(file_obj.data, dict) else {}
            display_name = str(data.get("name") or os.path.basename(data.get("path", "")) or media_type.capitalize()).strip()
            icon = QIcon()
            if media_type in ("image", "video"):
                thumb_path = GetThumbPath(file_obj.id, 1)
                if thumb_path and os.path.exists(thumb_path):
                    pix = QPixmap(thumb_path)
                    if not pix.isNull():
                        pix = pix.scaled(
                            96, 96, Qt.KeepAspectRatio, Qt.SmoothTransformation,
                        )
                        icon = QIcon(pix)
            elif media_type == "audio":
                icon = QIcon(os.path.join(info.PATH, "images", "AudioThumbnail.svg"))
            combo.addItem(icon, display_name, file_obj.id)

    def _populate_bundle_combo(self, combo):
        """Populate `combo` with every fbTools Reference Bundle (id -> display name),
        for a "bundle" extra_inputs entry -- e.g. picking a subject's own voice
        reference to feed a hand-built template's AUDIO input directly, in place of a
        Project-Files-backed media combo (there is no bundle concept in Project Files)."""
        if self.fbtools_client is None:
            return
        try:
            bundles = self.fbtools_client.list_bundles() or []
        except Exception as ex:
            log.warning("GenerateMediaDialog: list_bundles failed: %s", ex)
            return
        for bundle in bundles:
            if not isinstance(bundle, dict):
                continue
            label = bundle.get("name") or bundle.get("id", "")
            combo.addItem(str(label), bundle.get("id", ""))
            combo.setItemData(combo.count() - 1, str(bundle.get("path", "")), Qt.ToolTipRole)

    def _choose_media_from_project_files(self, combo, label, media_type):
        """Import a media file through the native chooser and select its Project Files ID."""
        media_type = str(media_type or "").strip().lower()
        filters = {
            "image": "Images (*.png *.jpg *.jpeg *.webp *.bmp *.tif *.tiff)",
            "video": "Videos (*.mp4 *.mov *.avi *.mkv *.webm)",
            "audio": "Audio (*.wav *.mp3 *.flac *.ogg *.m4a)",
        }
        path, _selected_filter = QFileDialog.getOpenFileName(
            self,
            "Choose {}".format(label),
            "",
            filters.get(media_type, "Media files (*)"),
        )
        if not path:
            return

        try:
            get_app().window.files_model.add_files(path, prevent_image_seq=True)
        except Exception as ex:
            log.warning("Unable to import selected generation input: %s", ex)
            QMessageBox.warning(self, "Import Failed", "Could not add the selected file to Project Files.")
            return

        file_obj = File.get(path=path)
        file_id = str(file_obj.id or "") if file_obj else ""
        if not file_id:
            QMessageBox.warning(self, "Import Failed", "The selected file was not added to Project Files.")
            return
        index = combo.findData(file_id)
        if index < 0:
            combo.addItem(os.path.basename(path), file_id)
            index = combo.findData(file_id)
        if index >= 0:
            combo.setCurrentIndex(index)

    def _choose_tracking_clicked(self):
        if not self.source_file:
            return

        win = SelectRegion(file=self.source_file, clip=None, selection_mode="annotate")
        if win.exec_() != QDialog.Accepted:
            return

        selection_payload = win.selection_payload()
        frame_size = win.videoPreview.curr_frame_size
        if not frame_size:
            frame_w = float(max(win.viewport_rect.width(), 1))
            frame_h = float(max(win.viewport_rect.height(), 1))
        else:
            frame_w = float(max(frame_size.width(), 1))
            frame_h = float(max(frame_size.height(), 1))
        src_w = float(max(getattr(win, "width", 1), 1))
        src_h = float(max(getattr(win, "height", 1), 1))

        def _scale_point_dict(p):
            if not isinstance(p, dict):
                return None
            try:
                x_in = float(p.get("x", 0.0))
                y_in = float(p.get("y", 0.0))
            except Exception:
                return None
            x_norm = max(min(x_in, float(max(frame_w - 1.0, 0.0))), 0.0)
            y_norm = max(min(y_in, float(max(frame_h - 1.0, 0.0))), 0.0)
            x_abs = int(round((x_norm / frame_w) * src_w))
            y_abs = int(round((y_norm / frame_h) * src_h))
            return {"x": x_abs, "y": y_abs}

        def _scale_rect_dict(r):
            if not isinstance(r, dict):
                return None
            try:
                x1_in = float(r.get("x1", 0.0))
                y1_in = float(r.get("y1", 0.0))
                x2_in = float(r.get("x2", 0.0))
                y2_in = float(r.get("y2", 0.0))
            except Exception:
                return None
            x1 = max(min(x1_in, float(max(frame_w - 1.0, 0.0))), 0.0)
            y1 = max(min(y1_in, float(max(frame_h - 1.0, 0.0))), 0.0)
            x2 = max(min(x2_in, float(max(frame_w - 1.0, 0.0))), 0.0)
            y2 = max(min(y2_in, float(max(frame_h - 1.0, 0.0))), 0.0)
            if x2 < x1:
                x1, x2 = x2, x1
            if y2 < y1:
                y1, y2 = y2, y1
            sx1 = int(round((x1 / frame_w) * src_w))
            sy1 = int(round((y1 / frame_h) * src_h))
            sx2 = int(round((x2 / frame_w) * src_w))
            sy2 = int(round((y2 / frame_h) * src_h))
            return {"x1": sx1, "y1": sy1, "x2": sx2, "y2": sy2}

        # Normalize all frame annotations to source frame coordinates.
        if isinstance(selection_payload, dict) and isinstance(selection_payload.get("frames"), dict):
            normalized_frames = {}
            for frame_key, frame_data in selection_payload.get("frames", {}).items():
                if not isinstance(frame_data, dict):
                    continue
                pos_pts = [_scale_point_dict(p) for p in (frame_data.get("positive_points") or [])]
                neg_pts = [_scale_point_dict(p) for p in (frame_data.get("negative_points") or [])]
                pos_rects = [_scale_rect_dict(r) for r in (frame_data.get("positive_rects") or [])]
                neg_rects = [_scale_rect_dict(r) for r in (frame_data.get("negative_rects") or [])]
                normalized_frames[str(frame_key)] = {
                    "positive_points": [p for p in pos_pts if p is not None],
                    "negative_points": [p for p in neg_pts if p is not None],
                    "positive_rects": [r for r in pos_rects if r is not None],
                    "negative_rects": [r for r in neg_rects if r is not None],
                }
            selection_payload["frames"] = normalized_frames

        frames = selection_payload.get("frames", {}) if isinstance(selection_payload, dict) else {}
        seed_frame = int(selection_payload.get("seed_frame", 1)) if isinstance(selection_payload, dict) else 1
        seed_data = frames.get(str(seed_frame), {}) if isinstance(frames, dict) else {}
        points_pos = list(seed_data.get("positive_points", []) or [])
        points_neg = list(seed_data.get("negative_points", []) or [])
        rects_pos = list(seed_data.get("positive_rects", []) or [])
        rects_neg = list(seed_data.get("negative_rects", []) or [])

        has_any_selection = bool(points_pos or points_neg or rects_pos or rects_neg)
        if not has_any_selection:
            QMessageBox.warning(
                self,
                "No Selections Found",
                "No points or rectangles were captured.",
            )
            return

        points_pos_text = json.dumps(points_pos) if points_pos else ""
        points_neg_text = json.dumps(points_neg) if points_neg else ""
        rects_pos_text = json.dumps(rects_pos) if rects_pos else ""
        rects_neg_text = json.dumps(rects_neg) if rects_neg else ""
        log.info(
            "Generate dialog captured SAM2 seed frame=%s points_pos=%s points_neg=%s rects_pos=%s rects_neg=%s",
            seed_frame,
            len(points_pos),
            len(points_neg),
            len(rects_pos),
            len(rects_neg),
        )
        self._coordinates_positive_text = points_pos_text
        self._coordinates_negative_text = points_neg_text
        self._rectangles_positive_text = rects_pos_text
        self._rectangles_negative_text = rects_neg_text
        self._auto_mode = False
        self._tracking_selection_payload = selection_payload if isinstance(selection_payload, dict) else {}
        self.points_preview.setPlainText(
            json.dumps(
                {
                    "seed_frame": seed_frame,
                    "auto_mode": False,
                    "positive": points_pos_text,
                    "negative": points_neg_text,
                    "positive_rects": rects_pos_text,
                    "negative_rects": rects_neg_text,
                    "tracking_selection": self._tracking_selection_payload,
                },
                indent=2,
            )
        )
        self.tabs.setCurrentWidget(self.page_points)

    def _clear_points_clicked(self):
        self._coordinates_positive_text = ""
        self._coordinates_negative_text = ""
        self._rectangles_positive_text = ""
        self._rectangles_negative_text = ""
        self._auto_mode = False
        self._tracking_selection_payload = {}
        self.points_preview.clear()

    def _set_tab_visible(self, index, visible):
        bar = self.tabs.tabBar()
        if hasattr(bar, "setTabVisible"):
            bar.setTabVisible(index, bool(visible))
        else:
            self.tabs.setTabEnabled(index, bool(visible))

    def _initialize_dialog_state(self):
        self._on_template_changed(self.template_combo.currentIndex())
