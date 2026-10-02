"""
 @file
 @brief Targeted unit tests for classes.query.file_is_on_timeline, shared by
        the Export dialog's duplicate-file detection and the Project Files
        thumbnail "used on timeline" badge.
"""

import importlib
import os
import sys
import types
import unittest
from unittest.mock import patch


PATH = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
if PATH not in sys.path:
    sys.path.append(PATH)


class FileIsOnTimelineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = importlib.import_module("classes.query")

    def test_true_when_a_clip_references_it(self):
        clip = types.SimpleNamespace(data={"file_id": "F1"})
        with patch.object(self.module.Clip, "filter", return_value=[clip]):
            self.assertTrue(self.module.file_is_on_timeline("F1"))

    def test_false_when_no_clip_references_it(self):
        clip = types.SimpleNamespace(data={"file_id": "F2"})
        with patch.object(self.module.Clip, "filter", return_value=[clip]):
            self.assertFalse(self.module.file_is_on_timeline("F1"))

    def test_false_for_empty_timeline(self):
        with patch.object(self.module.Clip, "filter", return_value=[]):
            self.assertFalse(self.module.file_is_on_timeline("F1"))

    def test_skips_clips_with_non_dict_data(self):
        # Defensive guard: a bare/uninitialized Clip object's .data isn't always a dict.
        clip = types.SimpleNamespace(data=None)
        with patch.object(self.module.Clip, "filter", return_value=[clip]):
            self.assertFalse(self.module.file_is_on_timeline("F1"))


if __name__ == "__main__":
    unittest.main()
