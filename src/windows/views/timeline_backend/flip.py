"""Mirror clips horizontally or vertically by negating their scale keyframes."""

import json

import openshot

from .enums import MenuFlip

# libopenshot places a clip using its signed scaled size, so a negative scale only
# mirrors in place when gravity is centered on the flipped axis.
_CENTERED_GRAVITY = {
    "scale_x": (openshot.GRAVITY_TOP, openshot.GRAVITY_CENTER, openshot.GRAVITY_BOTTOM),
    "scale_y": (openshot.GRAVITY_LEFT, openshot.GRAVITY_CENTER, openshot.GRAVITY_RIGHT),
}


def flip_property(action):
    """Return the scale keyframe that mirrors a clip for a MenuFlip action."""
    return "scale_x" if action == MenuFlip.HORIZONTAL else "scale_y"


def can_flip(clip_data, prop):
    """Return True when negating `prop` mirrors the clip without moving it off-frame."""
    if clip_data.get("scale") == openshot.SCALE_NONE:
        # Readers size SCALE_NONE frames from the max scale, which is negative here.
        return False
    return clip_data.get("gravity", openshot.GRAVITY_CENTER) in _CENTERED_GRAVITY[prop]


def is_flipped(clip_data, prop):
    """Return True when every keyframe point of `prop` is negative."""
    points = clip_data.get(prop, {}).get("Points", [])
    return bool(points) and all(point["co"]["Y"] < 0 for point in points)


def set_flipped(clip_data, prop, flipped):
    """Negate every point of `prop` (keeping animation) so the clip matches `flipped`."""
    if is_flipped(clip_data, prop) == flipped:
        return False
    points = clip_data.get(prop, {}).get("Points")
    if not points:
        point = openshot.Point(1, -1.0 if flipped else 1.0, openshot.BEZIER)
        clip_data[prop] = {"Points": [json.loads(point.Json())]}
        return True
    for point in points:
        point["co"]["Y"] = -point["co"]["Y"]
    return True
