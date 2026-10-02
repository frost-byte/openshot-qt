"""
 @file
 @brief This file reads a clip's embedded fbTools/ComfyUI generation metadata.
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
import shutil
import subprocess

from classes.logger import log


def _find_ffprobe():
    """Locate ffprobe on PATH. OpenShot itself renders through libopenshot's bundled FFmpeg
    (openshot.Clip/openshot.FFmpegWriter), so a standalone ffprobe binary is not otherwise a
    hard OpenShot dependency -- this probe is best-effort and simply does nothing when one isn't
    available (same stance fbTools' own utils/generation_metadata.py takes)."""
    return shutil.which("ffprobe") or shutil.which("ffprobe.exe")


def _read_format_tag(path, tag_name, ffprobe=None):
    exe = ffprobe or _find_ffprobe()
    if not exe:
        return None
    try:
        out = subprocess.run(
            [exe, "-v", "error", "-show_entries", "format_tags={}".format(tag_name),
             "-of", "default=noprint_wrappers=1:nokey=1", path],
            capture_output=True, text=True, timeout=30,
        )
        raw = out.stdout.strip()
        if not raw:
            return None
        data = json.loads(raw)
        return data if isinstance(data, dict) else None
    except (OSError, ValueError, subprocess.TimeoutExpired) as ex:
        log.debug("clip_cast_metadata: ffprobe tag read failed for %s (%s): %s", path, tag_name, ex)
        return None


def probe_cast_metadata(path, ffprobe=None):
    """Read a clip's embedded fbTools generation metadata directly from the local file -- no
    network call. Tries the full embedded ComfyUI "prompt" graph first (richest source); if
    that's absent (e.g. the clip was already cleaned, such as by fbTools' Kdenlive archiver),
    falls back to the lighter "fbtools_cast" summary tag fbTools writes onto cleaned clips.

    Returns {"prompt_graph": {...}} or {"cast_summary": {...}} -- the exact shape
    FBToolsClient.inspect_cast_metadata() expects -- or None if neither tag is present/readable.
    """
    if not path:
        return None
    exe = ffprobe or _find_ffprobe()
    if not exe:
        return None

    prompt_graph = _read_format_tag(path, "prompt", ffprobe=exe)
    if prompt_graph is not None:
        return {"prompt_graph": prompt_graph}

    cast_summary = _read_format_tag(path, "fbtools_cast", ffprobe=exe)
    if cast_summary is not None:
        return {"cast_summary": cast_summary}

    return None


def resolve_cast_metadata(fbtools_client, blob):
    """Resolve a probe_cast_metadata() blob against fbTools' inspect_cast_metadata endpoint.

    Returns the structured {"composition_name", "composition", "primary_subject",
    "primary_bundle", "tags", "note"} result, or None on any failure -- this is always a
    best-effort pre-fill, never a hard requirement for opening the Scene Cast builder.
    """
    if not isinstance(blob, dict) or fbtools_client is None:
        return None
    try:
        return fbtools_client.inspect_cast_metadata(
            prompt_graph=blob.get("prompt_graph"),
            cast_summary=blob.get("cast_summary"),
        )
    except Exception as ex:
        log.debug("clip_cast_metadata: resolve_cast_metadata failed: %s", ex)
        return None
