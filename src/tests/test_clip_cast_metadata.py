"""
 @file
 @brief Targeted unit tests for the local-ffprobe cast-metadata probe used by the
        Scene Cast Generation feature's pre-fill flow.
"""

import importlib
import os
import subprocess
import sys
import unittest
from unittest.mock import MagicMock, patch


PATH = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
if PATH not in sys.path:
    sys.path.append(PATH)


class ClipCastMetadataTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = importlib.import_module("classes.clip_cast_metadata")

    # ---- probe_cast_metadata ----

    def test_no_ffprobe_available_returns_none(self):
        with patch.object(self.module, "_find_ffprobe", return_value=None):
            result = self.module.probe_cast_metadata("/media/clip.mp4")
        self.assertIsNone(result)

    def test_no_path_returns_none_without_shelling_out(self):
        with patch.object(self.module, "_find_ffprobe") as find_ffprobe:
            result = self.module.probe_cast_metadata("")
        self.assertIsNone(result)
        find_ffprobe.assert_not_called()

    def test_prompt_tag_present_returns_prompt_graph(self):
        graph = {"1": {"class_type": "fbt_SceneCastBuild", "inputs": {}}}
        completed = MagicMock(stdout=__import__("json").dumps(graph) + "\n")
        with patch.object(self.module, "_find_ffprobe", return_value="/usr/bin/ffprobe"), \
                patch.object(subprocess, "run", return_value=completed) as run:
            result = self.module.probe_cast_metadata("/media/clip.mp4")
        self.assertEqual(result, {"prompt_graph": graph})
        # Only the "prompt" tag should be queried -- the summary fallback is unnecessary once
        # the richer tag is found.
        self.assertEqual(run.call_count, 1)
        self.assertIn("format_tags=prompt", run.call_args[0][0])

    def test_falls_back_to_cast_summary_tag_when_prompt_tag_absent(self):
        summary = {"composition": "wide_shot", "primary_subject": "alex",
                   "primary_bundle": "alex_bundle", "tags": ["alex_bundle"]}

        def fake_run(args, **kwargs):
            if "format_tags=prompt" in args:
                return MagicMock(stdout="")
            return MagicMock(stdout=__import__("json").dumps(summary) + "\n")

        with patch.object(self.module, "_find_ffprobe", return_value="/usr/bin/ffprobe"), \
                patch.object(subprocess, "run", side_effect=fake_run):
            result = self.module.probe_cast_metadata("/media/clip.mp4")
        self.assertEqual(result, {"cast_summary": summary})

    def test_neither_tag_present_returns_none(self):
        with patch.object(self.module, "_find_ffprobe", return_value="/usr/bin/ffprobe"), \
                patch.object(subprocess, "run", return_value=MagicMock(stdout="")):
            result = self.module.probe_cast_metadata("/media/clip.mp4")
        self.assertIsNone(result)

    def test_malformed_json_tag_is_treated_as_absent(self):
        with patch.object(self.module, "_find_ffprobe", return_value="/usr/bin/ffprobe"), \
                patch.object(subprocess, "run", return_value=MagicMock(stdout="not json")):
            result = self.module.probe_cast_metadata("/media/clip.mp4")
        self.assertIsNone(result)

    def test_ffprobe_timeout_treated_as_absent(self):
        with patch.object(self.module, "_find_ffprobe", return_value="/usr/bin/ffprobe"), \
                patch.object(subprocess, "run", side_effect=subprocess.TimeoutExpired(cmd="ffprobe", timeout=30)):
            result = self.module.probe_cast_metadata("/media/clip.mp4")
        self.assertIsNone(result)

    # ---- resolve_cast_metadata ----

    def test_resolve_posts_prompt_graph_blob(self):
        client = MagicMock()
        client.inspect_cast_metadata.return_value = {"composition_name": "wide_shot"}
        blob = {"prompt_graph": {"1": {}}}
        result = self.module.resolve_cast_metadata(client, blob)
        client.inspect_cast_metadata.assert_called_once_with(prompt_graph={"1": {}}, cast_summary=None)
        self.assertEqual(result, {"composition_name": "wide_shot"})

    def test_resolve_posts_cast_summary_blob(self):
        client = MagicMock()
        client.inspect_cast_metadata.return_value = {"composition_name": "wide_shot"}
        blob = {"cast_summary": {"composition": "wide_shot"}}
        self.module.resolve_cast_metadata(client, blob)
        client.inspect_cast_metadata.assert_called_once_with(prompt_graph=None, cast_summary={"composition": "wide_shot"})

    def test_resolve_none_blob_returns_none_without_calling_client(self):
        client = MagicMock()
        result = self.module.resolve_cast_metadata(client, None)
        self.assertIsNone(result)
        client.inspect_cast_metadata.assert_not_called()

    def test_resolve_none_client_returns_none(self):
        result = self.module.resolve_cast_metadata(None, {"prompt_graph": {}})
        self.assertIsNone(result)

    def test_resolve_swallows_client_exceptions(self):
        client = MagicMock()
        client.inspect_cast_metadata.side_effect = RuntimeError("fbTools unreachable")
        result = self.module.resolve_cast_metadata(client, {"prompt_graph": {}})
        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
