"""
 @file
 @brief Targeted unit tests for the Project Files thumbnail "used on timeline"
        badge painter.
"""

import os
import sys
import unittest
from unittest.mock import MagicMock


PATH = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
if PATH not in sys.path:
    sys.path.append(PATH)

from qt_api import QRectF
import windows.views.files_thumbnail_overlay as overlay


class PaintTimelineUsageBadgeTests(unittest.TestCase):
    def test_noop_when_not_on_timeline(self):
        painter = MagicMock()
        overlay.paint_timeline_usage_badge(painter, QRectF(0, 0, 80, 80), False)
        painter.save.assert_not_called()
        painter.drawEllipse.assert_not_called()

    def test_noop_when_rect_invalid(self):
        painter = MagicMock()
        overlay.paint_timeline_usage_badge(painter, QRectF(), True)
        painter.save.assert_not_called()

    def test_noop_when_rect_none(self):
        painter = MagicMock()
        overlay.paint_timeline_usage_badge(painter, None, True)
        painter.save.assert_not_called()

    def test_draws_badge_in_top_right_corner_when_on_timeline(self):
        painter = MagicMock()
        deco_rect = QRectF(0, 0, 80, 80)
        overlay.paint_timeline_usage_badge(painter, deco_rect, True)
        painter.save.assert_called_once()
        painter.restore.assert_called_once()
        painter.drawEllipse.assert_called_once()
        badge_rect = painter.drawEllipse.call_args[0][0]
        # Anchored to the top-right corner, not paint_proxy_badge's bottom-right.
        self.assertGreater(badge_rect.left(), deco_rect.center().x())
        self.assertLess(badge_rect.top(), deco_rect.center().y())
        self.assertEqual(painter.drawLine.call_count, 2)


if __name__ == "__main__":
    unittest.main()
