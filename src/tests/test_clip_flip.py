"""
 @file
 @brief This file contains unit tests for mirroring clips with negative scale
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
import sys
import tempfile
import unittest

import openshot
from qt_api import QApplication, QColor, QImage, QPainter

PATH = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
if PATH not in sys.path:
    sys.path.append(PATH)

from tests.qt_test_app import get_or_create_app
from windows.views.timeline_backend.enums import MenuFlip
from windows.views.timeline_backend.flip import can_flip, flip_property, is_flipped, set_flipped

app, _owns_app = get_or_create_app(lambda: QApplication([]))


def scale_keyframe(*values):
    points = []
    for index, value in enumerate(values):
        point = openshot.Point(1 + index * 30, value, openshot.BEZIER)
        points.append(json.loads(point.Json()))
    return {"Points": points}


def clip_data(gravity=openshot.GRAVITY_CENTER, scale=openshot.SCALE_FIT, scale_x=(1.0,), scale_y=(1.0,)):
    return {
        "gravity": gravity,
        "scale": scale,
        "scale_x": scale_keyframe(*scale_x),
        "scale_y": scale_keyframe(*scale_y),
    }


class ClipFlipHelperTests(unittest.TestCase):
    def test_flip_property_maps_actions_to_scale_axes(self):
        self.assertEqual(flip_property(MenuFlip.HORIZONTAL), "scale_x")
        self.assertEqual(flip_property(MenuFlip.VERTICAL), "scale_y")

    def test_can_flip_requires_gravity_centered_on_the_flip_axis(self):
        horizontal = {openshot.GRAVITY_TOP, openshot.GRAVITY_CENTER, openshot.GRAVITY_BOTTOM}
        vertical = {openshot.GRAVITY_LEFT, openshot.GRAVITY_CENTER, openshot.GRAVITY_RIGHT}
        for gravity in range(openshot.GRAVITY_TOP_LEFT, openshot.GRAVITY_BOTTOM_RIGHT + 1):
            with self.subTest(gravity=gravity):
                data = clip_data(gravity=gravity)
                self.assertEqual(can_flip(data, "scale_x"), gravity in horizontal)
                self.assertEqual(can_flip(data, "scale_y"), gravity in vertical)

    def test_can_flip_rejects_scale_none(self):
        data = clip_data(scale=openshot.SCALE_NONE)
        self.assertFalse(can_flip(data, "scale_x"))
        self.assertFalse(can_flip(data, "scale_y"))

    def test_set_flipped_negates_every_point_and_round_trips(self):
        data = clip_data(scale_x=(1.0, 2.5, 0.5))
        original = copy.deepcopy(data)

        self.assertTrue(set_flipped(data, "scale_x", True))
        self.assertEqual([p["co"]["Y"] for p in data["scale_x"]["Points"]], [-1.0, -2.5, -0.5])
        self.assertEqual([p["co"]["X"] for p in data["scale_x"]["Points"]], [1.0, 31.0, 61.0])
        self.assertTrue(is_flipped(data, "scale_x"))
        self.assertFalse(is_flipped(data, "scale_y"))
        self.assertEqual(data["scale_y"], original["scale_y"])

        self.assertFalse(set_flipped(data, "scale_x", True))
        self.assertTrue(set_flipped(data, "scale_x", False))
        self.assertEqual(data, original)

    def test_set_flipped_creates_a_keyframe_when_missing(self):
        data = {"gravity": openshot.GRAVITY_CENTER, "scale": openshot.SCALE_FIT}
        self.assertTrue(set_flipped(data, "scale_y", True))
        self.assertEqual(data["scale_y"]["Points"][0]["co"]["Y"], -1.0)
        self.assertTrue(is_flipped(data, "scale_y"))


class ClipFlipRenderTests(unittest.TestCase):
    """Guard the libopenshot behavior the flip relies on: negative scale mirrors in place."""

    def bounds(self, image, color):
        target = QColor(color)
        xs, ys = [], []
        for y in range(image.height()):
            for x in range(image.width()):
                pixel = image.pixelColor(x, y)
                if (abs(pixel.red() - target.red()) < 40 and abs(pixel.green() - target.green()) < 40
                        and abs(pixel.blue() - target.blue()) < 40 and pixel.alpha() > 200):
                    xs.append(x)
                    ys.append(y)
        return (min(xs), min(ys), max(xs), max(ys)) if xs else None

    def render(self, folder, data):
        timeline = openshot.Timeline(64, 36, openshot.Fraction(30, 1), 44100, 2, openshot.LAYOUT_STEREO)
        clip = openshot.Clip(os.path.join(folder, "source.png"))
        clip.gravity = data["gravity"]
        clip.scale = data["scale"]
        for prop in ("scale_x", "scale_y"):
            keyframe = openshot.Keyframe()
            keyframe.SetJson(json.dumps(data[prop]))
            setattr(clip, prop, keyframe)
        timeline.AddClip(clip)
        timeline.Open()
        path = os.path.join(folder, "frame.png")
        timeline.GetFrame(1).Save(path, 1.0)
        timeline.Close()
        return QImage(path)

    def test_flipped_clip_mirrors_in_place_for_supported_gravity(self):
        with tempfile.TemporaryDirectory() as folder:
            source = QImage(32, 18, QImage.Format.Format_RGBA8888)
            source.fill(QColor("blue"))
            painter = QPainter(source)
            painter.fillRect(0, 0, 8, 6, QColor("red"))
            painter.end()
            source.save(os.path.join(folder, "source.png"))

            for prop, gravity in (("scale_x", openshot.GRAVITY_CENTER), ("scale_x", openshot.GRAVITY_TOP),
                                  ("scale_y", openshot.GRAVITY_CENTER), ("scale_y", openshot.GRAVITY_LEFT)):
                with self.subTest(prop=prop, gravity=gravity):
                    data = clip_data(gravity=gravity)
                    normal = self.render(folder, data)
                    self.assertTrue(set_flipped(data, prop, True))
                    flipped = self.render(folder, data)

                    self.assertEqual(self.bounds(flipped, "blue"), self.bounds(normal, "blue"))
                    nx1, ny1, nx2, ny2 = self.bounds(normal, "red")
                    fx1, fy1, fx2, fy2 = self.bounds(flipped, "red")
                    if prop == "scale_x":
                        self.assertEqual((fy1, fy2), (ny1, ny2))
                        self.assertAlmostEqual(fx2, normal.width() - 1 - nx1, delta=1)
                    else:
                        self.assertEqual((fx1, fx2), (nx1, nx2))
                        self.assertAlmostEqual(fy2, normal.height() - 1 - ny1, delta=1)


if __name__ == "__main__":
    unittest.main()
