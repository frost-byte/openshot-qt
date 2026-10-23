"""
 @file
 @brief Tests for dropping embedded media metadata (ComfyUI workflows) from project data
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

import copy
import json
import os
import tempfile
import types
import unittest
from unittest.mock import patch

from classes import metadata_slim
from classes.metadata_slim import BACKUP_SUFFIX, slim_metadata, slim_project
from classes.project_data import ProjectDataStore
from classes.updates import UpdateManager
from tests.test_project_data import DummyAction, DummyApp, DummySettings, ensure_app_state
from tests.qt_test_app import get_or_create_app

WORKFLOW = json.dumps({"nodes": [{"id": n, "type": "GetNode"} for n in range(400)]})
PROMPT = json.dumps({str(n): {"inputs": {"text": "x" * 20}} for n in range(200)})


def media_metadata():
    return {"major_brand": "isom", "encoder": "Lavf63.1.102", "title": "Scene",
            "workflow": WORKFLOW, "prompt": PROMPT, "comment": "y" * 5000}


def comfy_project():
    reader = {"path": "compositions/a.mp4", "type": "FFmpegReader", "metadata": media_metadata()}
    clip = {"id": "C1", "file_id": "F1", "position": 0., "reader": copy.deepcopy(reader)}
    return {
        "files": [dict(reader, id="F1")],
        "clips": [clip],
        "history": {"undo": [{"type": "update", "key": ["clips", {"id": "C1"}],
                              "value": copy.deepcopy(clip), "old_values": copy.deepcopy(clip)}],
                    "redo": []},
    }


def all_metadata(data):
    found, stack = [], [data]
    while stack:
        item = stack.pop()
        if isinstance(item, dict):
            if isinstance(item.get("metadata"), dict):
                found.append(item["metadata"])
            stack.extend(item.values())
        elif isinstance(item, list):
            stack.extend(item)
    return found


class SlimMetadataTests(unittest.TestCase):
    def test_strips_workflow_prompt_and_large_text_everywhere(self):
        data = comfy_project()
        removed = slim_metadata(data)

        self.assertGreater(removed, len(WORKFLOW) * 4)
        metadata = all_metadata(data)
        # files, clip reader, undo value and undo old_values
        self.assertEqual(len(metadata), 4)
        for entry in metadata:
            self.assertEqual(entry, {"major_brand": "isom", "encoder": "Lavf63.1.102", "title": "Scene"})
        self.assertEqual(data["clips"][0]["reader"]["path"], "compositions/a.mp4")
        self.assertEqual(slim_metadata(data), 0)

    def test_dry_run_reports_without_changing_data(self):
        data = comfy_project()
        original = copy.deepcopy(data)
        self.assertGreater(slim_metadata(data, dry_run=True), 0)
        self.assertEqual(data, original)

    def test_slim_project_backs_up_once_before_changing_anything(self):
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "edit.osp")
            with open(path, "w") as handle:
                json.dump(comfy_project(), handle)
            data = comfy_project()

            self.assertTrue(slim_project(data, path))
            with open(path + BACKUP_SUFFIX) as handle:
                self.assertEqual(json.load(handle), comfy_project())

            # A later slim (new imports) never overwrites the first backup
            with open(path, "w") as handle:
                json.dump({"changed": True}, handle)
            self.assertTrue(slim_project(comfy_project(), path))
            with open(path + BACKUP_SUFFIX) as handle:
                self.assertEqual(json.load(handle), comfy_project())

            self.assertFalse(slim_project(data, path))

    def test_slim_project_keeps_data_when_backup_fails(self):
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "edit.osp")
            with open(path, "w") as handle:
                json.dump(comfy_project(), handle)
            data = comfy_project()
            with patch("classes.metadata_slim.shutil.copy2", side_effect=OSError("read-only")):
                self.assertFalse(slim_project(data, path))
            self.assertEqual(data, comfy_project())


class SlimOnUpdateTests(unittest.TestCase):
    def setUp(self):
        self.updates = UpdateManager()
        self.seen = []
        self.updates.add_listener(types.SimpleNamespace(changed=self.seen.append))

    def test_insert_and_update_slim_values_before_listeners_and_history(self):
        clip = comfy_project()["clips"][0]
        self.updates.insert(["clips"], clip)
        self.updates.update(["files", {"id": "F1"}], comfy_project()["files"][0])

        for action in self.seen:
            for entry in all_metadata(action.values):
                self.assertNotIn("workflow", entry)
                self.assertNotIn("prompt", entry)
        for action in self.updates.actionHistory:
            self.assertNotIn("workflow", json.dumps(action.values))
        # Callers keep a consistent view of what was saved
        self.assertNotIn("workflow", clip["reader"]["metadata"])

    def test_setting_off_keeps_metadata(self):
        clip = comfy_project()["clips"][0]
        with patch("classes.metadata_slim.slimming_enabled", return_value=False):
            self.updates.insert(["clips"], clip)
        self.assertIn("workflow", clip["reader"]["metadata"])

    def test_setting_lookup(self):
        app = types.SimpleNamespace(get_settings=lambda: DummySettings())
        with patch("classes.app.get_app", return_value=app):
            self.assertTrue(metadata_slim.slimming_enabled())
            app.get_settings = lambda: types.SimpleNamespace(get=lambda key: False)
            self.assertFalse(metadata_slim.slimming_enabled())


class SlimOnLoadTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        app, _owns_app = get_or_create_app(DummyApp)
        cls.app = ensure_app_state(app)

    def setUp(self):
        ensure_app_state(self.app)
        self.app.settings = DummySettings()
        self.app.window = types.SimpleNamespace(actionClearWaveformData=DummyAction())
        self.loaded = []
        self.app.updates = types.SimpleNamespace(load=self.loaded.append)
        self.addCleanup(ensure_app_state, self.app)

    def load(self, store, path):
        with patch.object(store, "check_if_paths_are_valid"), \
                patch.object(store, "add_to_recent_files"), \
                patch.object(store, "upgrade_project_data_structures"):
            store.load(path, clear_thumbnails=False)

    def test_load_slims_files_clips_and_history_and_marks_unsaved(self):
        with tempfile.TemporaryDirectory() as tmpdir, \
                patch("classes.project_data.info.USER_DEFAULT_PROJECT", os.path.join(tmpdir, "default.osp")):
            store = ProjectDataStore()
            saved = copy.deepcopy(store._data)
            saved.update(comfy_project())
            path = os.path.join(tmpdir, "comfy.osp")
            with open(path, "w") as handle:
                json.dump(saved, handle)

            self.load(store, path)

            self.assertTrue(store.has_unsaved_changes)
            self.assertTrue(os.path.isfile(path + BACKUP_SUFFIX))
            self.assertNotIn("workflow", json.dumps(store._data))
            self.assertEqual(len(store.get("history")["undo"]), 1)
            self.assertIs(self.loaded[-1], store._data)

            # Re-opening a slim project changes nothing and stays saved
            store.save(path)
            store.has_unsaved_changes = False
            self.load(store, path)
            self.assertFalse(store.has_unsaved_changes)

    def test_load_leaves_projects_alone_when_setting_is_off(self):
        self.app.settings.set("slim-media-metadata", False)
        with tempfile.TemporaryDirectory() as tmpdir, \
                patch("classes.project_data.info.USER_DEFAULT_PROJECT", os.path.join(tmpdir, "default.osp")):
            store = ProjectDataStore()
            saved = copy.deepcopy(store._data)
            saved.update(comfy_project())
            path = os.path.join(tmpdir, "comfy.osp")
            with open(path, "w") as handle:
                json.dump(saved, handle)

            self.load(store, path)

            self.assertFalse(store.has_unsaved_changes)
            self.assertFalse(os.path.exists(path + BACKUP_SUFFIX))
            self.assertIn("workflow", json.dumps(store._data))


if __name__ == "__main__":
    unittest.main()
