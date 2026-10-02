"""
 @file
 @brief Dynamic media-type overlay painter for project file thumbnails.
"""

import os

from qt_api import Qt, QRectF, QPointF
from qt_api import QPainter, QPen, QBrush, QColor
from qt_api import QSvgRenderer

from classes import info


_VIDEO_OVERLAY_ICON = "tool-media-play.svg"
_OPTIMIZE_PREVIEW_READY_ICON = "tool-optimize-preview.svg"
_OPTIMIZE_PREVIEW_MISSING_ICON = "tool-optimize-preview-missing.svg"


def _overlay_icon_path(media_type):
    if str(media_type or "").strip().lower() != "video":
        return ""
    return os.path.join(info.PATH, "themes", "cosmic", "images", _VIDEO_OVERLAY_ICON)


def paint_media_overlay(painter, deco_rect, media_type):
    """Paint a centered translucent play glyph for video thumbnails."""
    if not deco_rect or not deco_rect.isValid():
        return

    icon_path = _overlay_icon_path(media_type)
    if not icon_path or not os.path.exists(icon_path):
        return

    painter.save()
    painter.setRenderHint(QPainter.Antialiasing, True)
    painter.setOpacity(0.7)

    glyph_size = max(16.0, min(deco_rect.width(), deco_rect.height()) * 0.36)
    glyph_rect = QRectF(
        deco_rect.center().x() - (glyph_size / 2.0),
        deco_rect.center().y() - (glyph_size / 2.0),
        glyph_size,
        glyph_size,
    )
    renderer = QSvgRenderer(icon_path)
    renderer.render(painter, glyph_rect)

    painter.restore()


def paint_proxy_badge(painter, deco_rect, proxy_state):
    """Paint a bottom-right lightning badge for proxy-ready/missing files."""
    proxy_state = str(proxy_state or "").strip().lower()
    if proxy_state not in ("ready", "missing"):
        return
    if not deco_rect or not deco_rect.isValid():
        return

    icon_name = _OPTIMIZE_PREVIEW_MISSING_ICON if proxy_state == "missing" else _OPTIMIZE_PREVIEW_READY_ICON
    icon_path = os.path.join(info.PATH, "themes", "cosmic", "images", icon_name)
    if not os.path.exists(icon_path):
        return

    badge_size = max(14.0, min(deco_rect.width(), deco_rect.height()) * 0.24)
    margin_x = 1.5
    margin_y = 4.0
    glyph_rect = QRectF(
        deco_rect.right() - badge_size - margin_x,
        deco_rect.bottom() - badge_size - margin_y,
        badge_size,
        badge_size,
    )

    painter.save()
    painter.setRenderHint(QPainter.Antialiasing, True)
    painter.setOpacity(0.95)
    renderer = QSvgRenderer(icon_path)
    renderer.render(painter, glyph_rect)
    painter.restore()


_TIMELINE_BADGE_FILL = QColor("#2ECC71")
_TIMELINE_BADGE_RING = QColor(255, 255, 255, 220)
_TIMELINE_BADGE_CHECK = QColor("#FFFFFF")


def paint_timeline_usage_badge(painter, deco_rect, in_timeline):
    """Paint a top-right green checkmark badge for a file currently referenced by
    at least one clip on the timeline. Drawn directly (no SVG asset) in the corner
    opposite paint_proxy_badge's bottom-right proxy-state badge, so the two never
    overlap when a file is both proxy-cached and on the timeline."""
    if not in_timeline:
        return
    if not deco_rect or not deco_rect.isValid():
        return

    badge_size = max(14.0, min(deco_rect.width(), deco_rect.height()) * 0.26)
    margin = 2.0
    badge_rect = QRectF(
        deco_rect.right() - badge_size - margin,
        deco_rect.top() + margin,
        badge_size,
        badge_size,
    )

    painter.save()
    painter.setRenderHint(QPainter.Antialiasing, True)
    painter.setOpacity(0.95)

    ring_width = max(1.0, badge_size * 0.08)
    painter.setPen(QPen(_TIMELINE_BADGE_RING, ring_width))
    painter.setBrush(QBrush(_TIMELINE_BADGE_FILL))
    painter.drawEllipse(badge_rect)

    check_pen = QPen(_TIMELINE_BADGE_CHECK)
    check_pen.setWidthF(max(1.5, badge_size * 0.16))
    check_pen.setCapStyle(Qt.RoundCap)
    check_pen.setJoinStyle(Qt.RoundJoin)
    painter.setPen(check_pen)

    cx = badge_rect.center().x()
    cy = badge_rect.center().y()
    r = badge_size * 0.5
    p1 = QPointF(cx - r * 0.5, cy)
    p2 = QPointF(cx - r * 0.1, cy + r * 0.4)
    p3 = QPointF(cx + r * 0.5, cy - r * 0.35)
    painter.drawLine(p1, p2)
    painter.drawLine(p2, p3)

    painter.restore()
