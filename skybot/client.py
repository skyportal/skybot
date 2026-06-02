"""Generic SkyPortal API client.

One `SkyPortalClient` instance binds a base URL + token, so the same code talks
to any SkyPortal deployment (fritz.science, skyportal-icare.ijclab.in2p3.fr, …).
Instance-specific policy (taxonomy ids, group ids, program logic) lives in the
consuming bot (fritzbot, icarebot), NOT here.

Ported from fritzbot/lionsbot's module-level `fritz_api`; the only structural
change is module-globals → instance state so multiple instances coexist.

Every method returns the parsed `data` field on success and raises
`SkyPortalError` on a non-success response.
"""

from __future__ import annotations

import time
from typing import Any

import requests


class SkyPortalError(RuntimeError):
    pass


_RETRY_STATUS = (429, 502, 503, 504)


class SkyPortalClient:
    def __init__(
        self,
        base_url: str,
        token: str,
        *,
        name: str = "skyportal",
        timeout: float = 30.0,
        rate_delay_s: float = 0.12,
        max_retries: int = 3,
        session: requests.Session | None = None,
    ):
        if not base_url:
            raise ValueError("base_url is required")
        if not token:
            raise ValueError("token is required")
        self.name = name
        self.base_url = base_url.rstrip("/")
        self.api_base = f"{self.base_url}/api"
        self.timeout = timeout
        self.rate_delay_s = rate_delay_s
        self.max_retries = max_retries
        self._session = session or requests.Session()
        self._session.headers.update({"Authorization": f"token {token}"})

    # ── transport ────────────────────────────────────────────────────────────
    def _call(
        self,
        method: str,
        path: str,
        *,
        params: dict | None = None,
        json_body: dict | None = None,
        timeout: float | None = None,
    ) -> Any:
        url = f"{self.api_base}/{path.lstrip('/')}"
        to = self.timeout if timeout is None else timeout
        for attempt in range(self.max_retries):
            try:
                r = self._session.request(
                    method, url, params=params, json=json_body, timeout=to
                )
            except requests.RequestException as e:
                if attempt == self.max_retries - 1:
                    raise SkyPortalError(f"{method} {url} network error: {e}") from e
                time.sleep(1.5 * (attempt + 1))
                continue
            if r.status_code in _RETRY_STATUS and attempt < self.max_retries - 1:
                time.sleep(2.0 * (attempt + 1))
                continue
            try:
                body = r.json()
            except ValueError:
                raise SkyPortalError(
                    f"{method} {url}: non-JSON response ({r.status_code})"
                )
            if r.status_code >= 400 or body.get("status") != "success":
                raise SkyPortalError(f"{method} {url} failed [{r.status_code}]: {body}")
            if self.rate_delay_s:
                time.sleep(self.rate_delay_s)
            return body.get("data")
        raise SkyPortalError(f"{method} {url}: exhausted retries")

    # ── profile / config reads ────────────────────────────────────────────────
    def get_user_profile(self) -> dict:
        return self._call("GET", "user")

    def list_groups(self) -> list[dict]:
        data = self._call("GET", "groups")
        if isinstance(data, dict):
            seen: dict[int, dict] = {}
            for key in ("user_accessible_groups", "user_groups", "all_groups"):
                for g in data.get(key) or []:
                    if g.get("id") is not None:
                        seen.setdefault(g["id"], g)
            return list(seen.values())
        return data if isinstance(data, list) else []

    def list_filters(self) -> list[dict]:
        data = self._call("GET", "filters")
        return data if isinstance(data, list) else (data or {}).get("filters", [])

    def get_filter(self, filter_id: int) -> dict:
        data = self._call("GET", f"filters/{int(filter_id)}")
        return data.get("data", data) if isinstance(data, dict) else data

    def list_allocations(self, *, group_id: int | None = None) -> list[dict]:
        params = {"group_id": group_id} if group_id is not None else None
        data = self._call("GET", "allocation", params=params)
        return data if isinstance(data, list) else (data or {}).get("data", [])

    def list_instruments(self) -> list[dict]:
        data = self._call("GET", "instrument")
        return data if isinstance(data, list) else (data or {}).get("data", [])

    # ── candidate (scanning-page) reads ────────────────────────────────────────
    def get_candidates(
        self,
        *,
        filter_ids: list[int] | None = None,
        group_ids: list[int] | None = None,
        saved_status: str = "all",
        start_date: str | None = None,
        end_date: str | None = None,
        first_detection_after: str | None = None,
        last_detection_before: str | None = None,
        classifications: str | None = None,
        min_redshift: float | None = None,
        max_redshift: float | None = None,
        annotation_filter_list: str | None = None,
        num_per_page: int = 100,
        max_pages: int = 50,
    ) -> list[dict]:
        """Paginate /api/candidates. `saved_status`: "all" |
        "notSavedToAnySelected" | "savedToAnySelected". Dates bound when the
        candidate passed the filter (ISO 8601)."""
        base: dict[str, Any] = {
            "numPerPage": min(num_per_page, 500),
            "savedStatus": saved_status,
        }
        if filter_ids:
            base["filterIDs"] = ",".join(str(i) for i in filter_ids)
        if group_ids:
            base["groupIDs"] = ",".join(str(i) for i in group_ids)
        if start_date:
            base["startDate"] = start_date
        if end_date:
            base["endDate"] = end_date
        if first_detection_after:
            base["firstDetectionAfter"] = first_detection_after
        if last_detection_before:
            base["lastDetectionBefore"] = last_detection_before
        if classifications:
            base["classifications"] = classifications
        if min_redshift is not None:
            base["minRedshift"] = min_redshift
        if max_redshift is not None:
            base["maxRedshift"] = max_redshift
        if annotation_filter_list:
            base["annotationFilterList"] = annotation_filter_list

        out: list[dict] = []
        page = 1
        while page <= max_pages:
            data = (
                self._call("GET", "candidates", params={**base, "pageNumber": page})
                or {}
            )
            batch = data.get("candidates", []) or []
            out.extend(batch)
            total = data.get("totalMatches", len(out))
            if not batch or len(out) >= total:
                break
            page += 1
        return out

    # ── source reads ───────────────────────────────────────────────────────────
    def list_sources(
        self,
        *,
        group_ids: list[int] | None = None,
        saved_only: bool = True,
        num_per_page: int = 100,
        max_pages: int = 200,
        extra_params: dict | None = None,
    ) -> list[dict]:
        out: list[dict] = []
        page = 1
        while page <= max_pages:
            params: dict[str, Any] = {"numPerPage": num_per_page, "pageNumber": page}
            if group_ids:
                params["group_ids"] = ",".join(str(i) for i in group_ids)
            if extra_params:
                params.update(extra_params)
            data = self._call("GET", "sources", params=params) or {}
            batch = data.get("sources", []) or []
            if saved_only:
                batch = [s for s in batch if s.get("active", True)]
            out.extend(batch)
            total = data.get("totalMatches", len(out))
            if not batch or len(out) >= total:
                break
            page += 1
        return out

    def cone_search(
        self,
        *,
        ra: float,
        dec: float,
        radius_deg: float,
        group_ids: list[int] | None = None,
        num_per_page: int = 100,
    ) -> list[dict]:
        params: dict[str, Any] = {
            "ra": ra,
            "dec": dec,
            "radius": radius_deg,
            "numPerPage": num_per_page,
            "pageNumber": 1,
        }
        if group_ids:
            params["group_ids"] = ",".join(str(i) for i in group_ids)
        data = self._call("GET", "sources", params=params) or {}
        return data.get("sources", []) or []

    def get_source(
        self,
        obj_id: str,
        *,
        include_thumbnails: bool = True,
        include_comments: bool = False,
        include_classifications: bool = False,
        include_detection_stats: bool = True,
    ) -> dict:
        params = {
            "includeRequested": "true",
            "includeThumbnails": str(include_thumbnails).lower(),
            "includeComments": str(include_comments).lower(),
            "includeClassifications": str(include_classifications).lower(),
            "includeDetectionStats": str(include_detection_stats).lower(),
        }
        return self._call("GET", f"sources/{obj_id}", params=params)

    def source_exists(self, obj_id: str) -> bool:
        try:
            self._call(
                "GET", f"sources/{obj_id}", params={"includeThumbnails": "false"}
            )
            return True
        except SkyPortalError:
            return False

    def get_photometry(self, obj_id: str) -> list[dict]:
        return self._call("GET", f"sources/{obj_id}/photometry") or []

    def get_spectra(self, obj_id: str) -> list[dict]:
        data = self._call("GET", f"sources/{obj_id}/spectra") or {}
        return data.get("spectra", []) if isinstance(data, dict) else data

    def get_annotations(self, obj_id: str) -> list[dict]:
        return self._call("GET", f"sources/{obj_id}/annotations") or []

    def get_thumbnails(self, obj_id: str) -> list[dict]:
        return self.get_source(obj_id).get("thumbnails") or []

    def get_comments(self, obj_id: str) -> list[dict]:
        return self._call("GET", f"sources/{obj_id}/comments") or []

    def get_classifications(self, obj_id: str) -> list[dict]:
        data = self._call("GET", f"sources/{obj_id}/classifications") or []
        return (
            data if isinstance(data, list) else (data or {}).get("classifications", [])
        )

    # ── observing runs / assignments ───────────────────────────────────────────
    def list_observing_runs(self) -> list[dict]:
        data = self._call("GET", "observing_run") or []
        return (
            data if isinstance(data, list) else (data or {}).get("observing_runs", [])
        )

    def list_assignments(self, run_id: int) -> list[dict]:
        run = self._call("GET", f"observing_run/{run_id}") or {}
        return run.get("assignments") or []

    def submit_assignment(
        self, *, run_id: int, obj_id: str, priority: int, comment: str | None = None
    ) -> dict:
        body: dict[str, Any] = {
            "obj_id": obj_id,
            "run_id": run_id,
            "priority": str(int(priority)),
        }
        if comment:
            body["comment"] = comment
        return self._call("POST", "assignment", json_body=body)

    def update_assignment(
        self,
        assignment_id: int,
        *,
        priority: int | None = None,
        comment: str | None = None,
    ) -> dict:
        body: dict[str, Any] = {}
        if priority is not None:
            body["priority"] = str(int(priority))
        if comment is not None:
            body["comment"] = comment
        if not body:
            raise ValueError("update_assignment: nothing to update")
        return self._call("PUT", f"assignment/{assignment_id}", json_body=body) or {}

    def delete_assignment(self, assignment_id: int) -> dict:
        return self._call("DELETE", f"assignment/{assignment_id}") or {}

    # ── followup requests ──────────────────────────────────────────────────────
    def get_followup_requests(self, obj_id: str) -> list[dict]:
        data = self._call("GET", "followup_request", params={"sourceID": obj_id}) or {}
        return data.get("followup_requests", []) if isinstance(data, dict) else data

    def get_followup_request(self, request_id: int) -> dict | None:
        try:
            return self._call("GET", f"followup_request/{int(request_id)}")
        except SkyPortalError:
            return None

    def submit_followup(
        self,
        *,
        allocation_id: int,
        obj_id: str,
        payload: dict,
        target_group_ids: list[int] | None = None,
    ) -> dict:
        body: dict[str, Any] = {
            "allocation_id": allocation_id,
            "obj_id": obj_id,
            "payload": payload,
        }
        if target_group_ids:
            body["target_group_ids"] = target_group_ids
        return self._call("POST", "followup_request", json_body=body)

    def delete_followup_request(self, request_id: int) -> dict:
        return self._call("DELETE", f"followup_request/{int(request_id)}") or {}

    # ── writes: classifications / comments / annotations / redshift / save ──────
    def submit_classification(
        self,
        *,
        obj_id: str,
        classification: str,
        taxonomy_id: int,
        probability: float = 0.7,
        group_ids: list[int] | None = None,
        origin: str = "skybot",
    ) -> dict:
        """Post a classification. `taxonomy_id` is REQUIRED and instance-specific
        (Fritz sitewide = 1018; ICARE may differ) — the caller supplies it."""
        body: dict[str, Any] = {
            "obj_id": obj_id,
            "classification": classification,
            "taxonomy_id": int(taxonomy_id),
            "probability": float(probability),
            "origin": origin,
        }
        if group_ids:
            body["group_ids"] = group_ids
        return self._call("POST", "classification", json_body=body)

    def list_taxonomies(self) -> list[dict]:
        data = self._call("GET", "taxonomy") or []
        return data if isinstance(data, list) else (data or {}).get("taxonomy", [])

    def post_comment(
        self, obj_id: str, text: str, *, group_ids: list[int] | None = None
    ) -> dict:
        body: dict[str, Any] = {"text": text}
        if group_ids:
            body["group_ids"] = group_ids
        return self._call("POST", f"sources/{obj_id}/comments", json_body=body)

    def post_annotation(
        self,
        obj_id: str,
        data: dict,
        *,
        origin: str = "skybot",
        group_ids: list[int] | None = None,
    ) -> dict:
        body: dict[str, Any] = {"origin": origin, "data": data}
        if group_ids:
            body["group_ids"] = group_ids
        return self._call("POST", f"sources/{obj_id}/annotations", json_body=body)

    def set_redshift(
        self, obj_id: str, redshift: float, *, redshift_error: float | None = None
    ) -> dict:
        """PATCH a source's redshift (and optional error)."""
        body: dict[str, Any] = {"redshift": float(redshift)}
        if redshift_error is not None:
            body["redshift_error"] = float(redshift_error)
        return self._call("PATCH", f"sources/{obj_id}", json_body=body) or {}

    def save_source(self, *, obj_id: str, group_ids: list[int]) -> dict:
        """Save an existing candidate to one or more groups."""
        return self._call(
            "POST", "sources", json_body={"id": obj_id, "group_ids": group_ids}
        )

    # ── photometry ─────────────────────────────────────────────────────────────
    _PHOT_FIELDS = (
        "mjd",
        "filter",
        "mag",
        "magerr",
        "limiting_mag",
        "magsys",
        "instrument_id",
        "ra",
        "dec",
        "altdata",
        "origin",
    )

    def post_photometry(
        self,
        obj_id: str,
        rows: list[dict],
        *,
        instrument_id: int | None = None,
        magsys: str = "ab",
        group_ids: list[int] | None = None,
        origin: str | None = None,
    ) -> list[dict]:
        """Post photometry points. `rows` is a list of dicts; each needs at least
        `mjd` + `filter` and either (`mag` + `magerr`) for a detection or
        `limiting_mag` for an upper limit. Per-row keys override the call-level
        defaults (`instrument_id`, `magsys`, `origin`). One POST per row so rows
        from different instruments/origins (typical for GCN-sourced photometry)
        can be mixed freely. Returns one response per row."""
        out: list[dict] = []
        for r in rows:
            body: dict[str, Any] = {"obj_id": obj_id}
            iid = r.get("instrument_id", instrument_id)
            if iid is None:
                raise ValueError(
                    "post_photometry: instrument_id required (per-row or as default)"
                )
            body["instrument_id"] = int(iid)
            body["magsys"] = r.get("magsys", magsys)
            for k in (
                "mjd",
                "filter",
                "mag",
                "magerr",
                "limiting_mag",
                "ra",
                "dec",
                "altdata",
            ):
                if r.get(k) is not None:
                    body[k] = r[k]
            org = r.get("origin", origin)
            if org is not None:
                body["origin"] = org
            gids = r.get("group_ids", group_ids)
            if gids:
                body["group_ids"] = gids
            out.append(self._call("POST", "photometry", json_body=body))
        return out

    # ── helpers ────────────────────────────────────────────────────────────────
    def find_allocation(
        self,
        *,
        instrument_name: str | None = None,
        instrument_id: int | None = None,
        preferred_group_id: int | None = None,
        preferred_pis: set[str] | None = None,
    ) -> dict | None:
        """Pick an allocation by instrument, optionally preferring a group/PI.
        Generic version of fritzbot's find_sedm_allocation."""
        allocs = self.list_allocations()
        match = [
            a
            for a in allocs
            if (
                instrument_name is not None
                and (a.get("instrument") or {}).get("name") == instrument_name
            )
            or (instrument_id is not None and a.get("instrument_id") == instrument_id)
        ]
        if not match:
            return None
        if preferred_group_id is not None:
            g = [a for a in match if a.get("group_id") == preferred_group_id]
            if g:
                return g[0]
        if preferred_pis:
            p = [a for a in match if a.get("pi") in preferred_pis]
            if p:
                return p[0]
        return match[0]
