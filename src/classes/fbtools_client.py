"""
 @file
 @brief This file contains a small REST client for fbTools' ComfyUI custom-node endpoints.
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
from urllib.request import Request
from urllib.parse import urlencode

from classes.comfy_client import urlopen
from classes.logger import log


class FBToolsClient:
    """Minimal REST client for the fbTools custom-node endpoints (`/fbtools/...`), served by the
    same ComfyUI instance ComfyClient already talks to -- no separate URL/config needed. Used by
    the Scene Cast builder (windows/scene_cast_builder.py) to list Compositions/Bundles/Subjects/
    Backgrounds, and by classes/clip_cast_metadata.py to resolve a clip's embedded metadata.

    Every method returns plain dicts/lists straight from the JSON response, or raises
    RuntimeError on a non-2xx/invalid-JSON response -- callers decide how tolerant to be (the
    metadata-probe path treats any failure as "nothing to pre-fill"; the builder dialog surfaces
    a real error if the user explicitly asked to list something).
    """

    def __init__(self, base_url):
        self.base_url = str(base_url or "").rstrip("/")

    def _get(self, path, params=None):
        url = "{}{}".format(self.base_url, path)
        if params:
            url = "{}?{}".format(url, urlencode(params))
        try:
            with urlopen(url, timeout=8.0) as response:
                return json.loads(response.read().decode("utf-8"))
        except Exception as ex:
            log.warning("FBToolsClient GET %s failed: %s", path, ex)
            raise RuntimeError("fbTools request failed: {}".format(ex))

    def _post(self, path, payload):
        url = "{}{}".format(self.base_url, path)
        req = Request(
            url,
            data=json.dumps(payload or {}).encode("utf-8"),
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        try:
            with urlopen(req, timeout=8.0) as response:
                return json.loads(response.read().decode("utf-8"))
        except Exception as ex:
            log.warning("FBToolsClient POST %s failed: %s", path, ex)
            raise RuntimeError("fbTools request failed: {}".format(ex))

    def list_compositions(self):
        """Return the list of composition summaries (`{id, name, model_type, ...}`)."""
        data = self._get("/fbtools/compositions/list")
        items = data.get("compositions", []) if isinstance(data, dict) else []
        return items if isinstance(items, list) else []

    def get_composition(self, composition_id):
        """Return the full composition dict for `composition_id`."""
        return self._get("/fbtools/compositions/get", {"id": composition_id})

    def list_bundles(self):
        data = self._get("/fbtools/bundles/list")
        items = data.get("bundles", data) if isinstance(data, dict) else data
        return items if isinstance(items, list) else []

    def list_subjects(self):
        data = self._get("/fbtools/subjects/list")
        items = data.get("subjects", data) if isinstance(data, dict) else data
        return items if isinstance(items, list) else []

    def list_backgrounds(self):
        data = self._get("/fbtools/backgrounds/list")
        items = data.get("backgrounds", data) if isinstance(data, dict) else data
        return items if isinstance(items, list) else []

    def inspect_cast_metadata(self, prompt_graph=None, cast_summary=None):
        """POST a clip's locally-read embedded metadata and get back the resolved
        {composition_name, composition, primary_subject, primary_bundle, tags, note}."""
        payload = {}
        if prompt_graph is not None:
            payload["prompt_graph"] = prompt_graph
        if cast_summary is not None:
            payload["cast_summary"] = cast_summary
        return self._post("/fbtools/compositions/inspect_cast_metadata", payload)
