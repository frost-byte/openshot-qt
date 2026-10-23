"""
 @file
 @brief Drop large embedded media metadata (e.g. ComfyUI workflows) from project data
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
import shutil

from classes.logger import log

# ComfyUI embeds its whole graph and prompt in every video it saves. libopenshot
# exposes container metadata in each reader's JSON, which OpenShot copies into
# every file, clip and undo entry. Nothing in OpenShot reads these values, and
# the media files keep them, so the project copy can be dropped.
SLIM_KEYS = frozenset({"workflow", "prompt"})
MAX_METADATA_TEXT = 4096
BACKUP_SUFFIX = ".pre-slim"


def slimming_enabled():
    try:
        from classes.app import get_app
        settings = get_app().get_settings()
        value = settings.get("slim-media-metadata")
    except Exception:
        return True
    return value is not False


def _oversized(key, value):
    return key in SLIM_KEYS or (isinstance(value, str) and len(value) > MAX_METADATA_TEXT)


def slim_metadata(data, dry_run=False):
    """Remove oversized values from every "metadata" dict inside data, in place.

    Returns the approximate number of characters removed (or removable, for a dry run).
    """
    removed = 0
    stack = [data]
    while stack:
        item = stack.pop()
        if isinstance(item, dict):
            metadata = item.get("metadata")
            if isinstance(metadata, dict):
                for key in [k for k, v in metadata.items() if _oversized(k, v)]:
                    value = metadata[key]
                    removed += len(value) if isinstance(value, str) else len(str(value))
                    if not dry_run:
                        del metadata[key]
            stack.extend(value for value in item.values() if isinstance(value, (dict, list)))
        elif isinstance(item, list):
            stack.extend(value for value in item if isinstance(value, (dict, list)))
    return removed


def slim_project(project_data, file_path=None):
    """Slim a loaded project, backing up the original file first. Returns True if changed.

    Nothing is removed when the backup cannot be written.
    """
    if not slim_metadata(project_data, dry_run=True):
        return False
    if file_path and os.path.isfile(file_path):
        backup = file_path + BACKUP_SUFFIX
        if not os.path.exists(backup):
            try:
                shutil.copy2(file_path, backup)
            except OSError as ex:
                log.warning("Not slimming metadata: unable to back up %s (%s)", file_path, ex)
                return False
            log.info("Backed up %s before slimming metadata", backup)
    removed = slim_metadata(project_data)
    log.info("Removed %.1f MB of embedded media metadata from project data", removed / 2**20)
    return True
