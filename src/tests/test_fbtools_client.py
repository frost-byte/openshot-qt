"""
 @file
 @brief Targeted unit tests for the fbTools REST client used by the Scene Cast
        Generation feature.
"""

import importlib
import json
import os
import sys
import unittest
from unittest.mock import MagicMock, patch


PATH = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
if PATH not in sys.path:
    sys.path.append(PATH)


def _fake_response(payload):
    response = MagicMock()
    response.read.return_value = json.dumps(payload).encode("utf-8")
    response.__enter__ = MagicMock(return_value=response)
    response.__exit__ = MagicMock(return_value=False)
    return response


def _fake_bytes_response(data):
    response = MagicMock()
    response.read.return_value = data
    response.__enter__ = MagicMock(return_value=response)
    response.__exit__ = MagicMock(return_value=False)
    return response


class FBToolsClientTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = importlib.import_module("classes.fbtools_client")

    def _client(self):
        return self.module.FBToolsClient("http://127.0.0.1:8188")

    def test_base_url_strips_trailing_slash(self):
        client = self.module.FBToolsClient("http://127.0.0.1:8188/")
        self.assertEqual(client.base_url, "http://127.0.0.1:8188")

    def test_list_compositions_returns_items(self):
        client = self._client()
        with patch.object(self.module, "urlopen", return_value=_fake_response(
                {"compositions": [{"id": "wide_shot", "name": "Wide Shot"}]})) as urlopen:
            result = client.list_compositions()
        self.assertEqual(result, [{"id": "wide_shot", "name": "Wide Shot"}])
        requested_url = urlopen.call_args[0][0]
        self.assertEqual(requested_url, "http://127.0.0.1:8188/fbtools/compositions/list")

    def test_list_compositions_tolerates_missing_key(self):
        client = self._client()
        with patch.object(self.module, "urlopen", return_value=_fake_response({})):
            result = client.list_compositions()
        self.assertEqual(result, [])

    def test_get_composition_passes_id_as_query_param(self):
        client = self._client()
        with patch.object(self.module, "urlopen", return_value=_fake_response(
                {"id": "wide_shot", "subjects": {"A": "alex"}})) as urlopen:
            result = client.get_composition("wide_shot")
        self.assertEqual(result, {"id": "wide_shot", "subjects": {"A": "alex"}})
        requested_url = urlopen.call_args[0][0]
        self.assertEqual(requested_url, "http://127.0.0.1:8188/fbtools/compositions/get?id=wide_shot")

    def test_list_bundles_accepts_bare_list_response(self):
        client = self._client()
        with patch.object(self.module, "urlopen", return_value=_fake_response([{"id": "b1"}])):
            result = client.list_bundles()
        self.assertEqual(result, [{"id": "b1"}])

    def test_list_subjects_accepts_wrapped_response(self):
        client = self._client()
        with patch.object(self.module, "urlopen", return_value=_fake_response({"subjects": [{"id": "s1"}]})):
            result = client.list_subjects()
        self.assertEqual(result, [{"id": "s1"}])

    def test_list_backgrounds_accepts_wrapped_response(self):
        client = self._client()
        with patch.object(self.module, "urlopen", return_value=_fake_response({"backgrounds": [{"id": "bg1"}]})):
            result = client.list_backgrounds()
        self.assertEqual(result, [{"id": "bg1"}])

    def test_list_source_profiles_accepts_wrapped_response(self):
        client = self._client()
        with patch.object(self.module, "urlopen", return_value=_fake_response(
                {"profiles": [{"id": "team_fort", "name": "Team Fort"}]})):
            result = client.list_source_profiles()
        self.assertEqual(result, [{"id": "team_fort", "name": "Team Fort"}])

    def test_get_source_profile_passes_id_as_query_param(self):
        client = self._client()
        with patch.object(self.module, "urlopen", return_value=_fake_response(
                {"id": "team_fort", "clips": [{"id": "clip_3", "subjects": ["s1"]}]})) as urlopen:
            result = client.get_source_profile("team_fort")
        self.assertEqual(result, {"id": "team_fort", "clips": [{"id": "clip_3", "subjects": ["s1"]}]})
        requested_url = urlopen.call_args[0][0]
        self.assertEqual(requested_url, "http://127.0.0.1:8188/fbtools/source_profiles/get?id=team_fort")

    def test_get_source_profile_frame_passes_query_params_and_returns_raw_bytes(self):
        client = self._client()
        jpeg_bytes = b"\xff\xd8\xff\xe0fakejpegdata"
        with patch.object(self.module, "urlopen", return_value=_fake_bytes_response(jpeg_bytes)) as urlopen:
            result = client.get_source_profile_frame("team_fort", 1.5, width=160)
        self.assertEqual(result, jpeg_bytes)
        requested_url = urlopen.call_args[0][0]
        self.assertEqual(
            requested_url,
            "http://127.0.0.1:8188/fbtools/source_profiles/frame_at?profile_id=team_fort&t=1.5&w=160",
        )

    def test_get_source_profile_frame_raises_runtime_error_on_failure(self):
        client = self._client()
        with patch.object(self.module, "urlopen", side_effect=OSError("connection refused")):
            with self.assertRaises(RuntimeError):
                client.get_source_profile_frame("team_fort", 1.5)

    def test_get_raises_runtime_error_on_failure(self):
        client = self._client()
        with patch.object(self.module, "urlopen", side_effect=OSError("connection refused")):
            with self.assertRaises(RuntimeError):
                client.list_compositions()

    def test_inspect_cast_metadata_posts_prompt_graph(self):
        client = self._client()
        with patch.object(self.module, "Request") as request_cls, \
                patch.object(self.module, "urlopen", return_value=_fake_response({"composition_name": "wide_shot"})):
            result = client.inspect_cast_metadata(prompt_graph={"1": {}})
        self.assertEqual(result, {"composition_name": "wide_shot"})
        request_cls.assert_called_once()
        _, kwargs = request_cls.call_args
        self.assertEqual(json.loads(kwargs["data"].decode("utf-8")), {"prompt_graph": {"1": {}}})
        self.assertEqual(kwargs["method"], "POST")

    def test_inspect_cast_metadata_posts_cast_summary_when_no_prompt_graph(self):
        client = self._client()
        with patch.object(self.module, "Request") as request_cls, \
                patch.object(self.module, "urlopen", return_value=_fake_response({"composition_name": "wide_shot"})):
            client.inspect_cast_metadata(cast_summary={"composition": "wide_shot"})
        _, kwargs = request_cls.call_args
        self.assertEqual(json.loads(kwargs["data"].decode("utf-8")), {"cast_summary": {"composition": "wide_shot"}})

    def test_post_raises_runtime_error_on_failure(self):
        client = self._client()
        with patch.object(self.module, "urlopen", side_effect=OSError("connection refused")):
            with self.assertRaises(RuntimeError):
                client.inspect_cast_metadata(prompt_graph={})


if __name__ == "__main__":
    unittest.main()
