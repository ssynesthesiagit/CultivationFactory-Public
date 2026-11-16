# Historical functions from APP/app/api.py at commit 65cf60c992c1da43038f64bdbafa1b53ad090a09.
# The test compiles these definitions with the current endpoint's closure.
from __future__ import annotations

def _library_identity(project_id: str, workflow: dict[str, Any] | None) -> dict[str, Any]:
    """Bounded identity facts for a library card, read without loading project payloads.

    Name and title come from the accepted (then AI-proposed) identity
    wording of the newest run, or the owner's display-name lock; target
    CL, Background and Paths come from the project's small owner locks.
    Everything is read through SQLite JSON functions so the multi-megabyte
    project and run documents never pass through Python.
    """
    identity: dict[str, Any] = {"name": None, "title": None, "target_cl": None, "background": None, "paths": [], "last_worked_at": None}
    with character_creation.db.connection() as conn:
        run = conn.execute(
            """SELECT COALESCE(json_extract(accepted_descriptive_fields_json, '$.identity.name'), json_extract(owner_descriptive_fields_json, '$.identity.name')) AS name,
                      COALESCE(json_extract(accepted_descriptive_fields_json, '$.identity.title'), json_extract(owner_descriptive_fields_json, '$.identity.title')) AS title,
                      updated_at
               FROM character_creation_runs WHERE project_id=? ORDER BY updated_at DESC LIMIT 1""",
            (project_id,),
        ).fetchone()
        if run:
            identity["name"] = run["name"] if isinstance(run["name"], str) and run["name"].strip() else None
            identity["title"] = run["title"] if isinstance(run["title"], str) and run["title"].strip() else None
            identity["last_worked_at"] = run["updated_at"]
        for row in conn.execute(
            """SELECT json_extract(l.value, '$.field') AS field, l.value AS lock_json
               FROM projects p, json_each(p.project_json, '$.user_locks') l
               WHERE p.project_id=? AND json_extract(l.value, '$.field') IN ('target_cl', 'character.identity.display_name', 'character_sheet.locked_choices')""",
            (project_id,),
        ):
            try:
                value = json.loads(row["lock_json"]).get("value")
            except (TypeError, ValueError):
                continue
            if row["field"] == "target_cl" and type(value) is int:
                identity["target_cl"] = value
            elif row["field"] == "character.identity.display_name" and isinstance(value, str) and value.strip() and not identity["name"]:
                identity["name"] = value.strip()
            elif row["field"] == "character_sheet.locked_choices" and isinstance(value, dict):
                background = value.get("background_choice")
                if isinstance(background, list) and background and isinstance(background[0], str):
                    identity["background"] = background[0].rsplit(".", 1)[-1].replace("_", " ").title()
                paths = value.get("path_choice")
                if isinstance(paths, list):
                    identity["paths"] = [
                        _OWNER_PATH_NAMES.get(path_id, path_id.rsplit(".", 1)[-1].replace("_", " ").title())
                        for path_id in paths if isinstance(path_id, str)
                    ]
    active_run = workflow.get("active_run") if isinstance(workflow, dict) else None
    if isinstance(active_run, dict) and isinstance(active_run.get("updated_at"), str):
        identity["last_worked_at"] = max(str(identity["last_worked_at"] or ""), active_run["updated_at"]) or None
    return identity


def _library_cached_facts(stamps: dict[str, tuple]) -> tuple[dict[str, str], dict[str, Any]]:
    completed_at_by_project: dict[str, str] = {}
    identity_by_project: dict[str, Any] = {}
    for project_id, stamp in stamps.items():
        cached = _library_identity_cache.get(project_id)
        if cached is None or cached[0] != stamp:
            completed = None
            try:
                with projects.db.connection() as conn:
                    row = conn.execute(
                        """SELECT MAX(completed_at) AS completed_at FROM character_creation_runs
                            WHERE project_id = ? AND status = 'CLEAN_AND_FINALIZED' AND completed_at IS NOT NULL""",
                        (project_id,),
                    ).fetchone()
                completed = row["completed_at"] if row and isinstance(row["completed_at"], str) and row["completed_at"] else None
            except Exception:
                completed = None
            cached = (stamp, {"completed_at": completed, "identity": None})
            _library_identity_cache[project_id] = cached
        if cached[1]["completed_at"]:
            completed_at_by_project[project_id] = cached[1]["completed_at"]
        identity_by_project[project_id] = cached
    return completed_at_by_project, identity_by_project


def character_library() -> list[dict[str, Any]]:
    archived_project_ids = character_library_archives.archived_project_ids()
    recoveries = {
        str(item.get("project_id")): item
        for item in character_creation.recoverable()
        if isinstance(item, dict) and item.get("project_id")
    }
    # The true completion time of each project's latest finalized run.
    # project.updated_at moves on any later touch, so it cannot answer
    # "when was this character finished".  Both it and the card identity are
    # cached per project until that project's change markers move (reading
    # them walks multi-megabyte run records).
    _library_cache_lock.acquire()
    try:
        stamps = _project_fingerprints()
        completed_at_by_project, identity_by_project = _library_cached_facts(stamps)
    finally:
        _library_cache_lock.release()
    result: list[dict[str, Any]] = []
    for project in projects.list_projects():
        project_id = project.get("project_id")
        if not isinstance(project_id, str) or not project_id:
            continue
        if project_id in archived_project_ids:
            continue
        workflow = recoveries.get(project_id) or {
            "schema": "TianxiaFoundry.CharacterCreationRecovery.v1",
            "project_id": project_id,
            "active": False,
            "active_run": None,
            "latest_run": None,
        }
        active_run = workflow.get("active_run") if isinstance(workflow, dict) else None
        latest_run = workflow.get("latest_run") if isinstance(workflow, dict) else None
        build_status = (
            active_run.get("status")
            if isinstance(active_run, dict) and active_run.get("status")
            else latest_run.get("status")
            if isinstance(latest_run, dict) and latest_run.get("status")
            else project.get("compile_status") or project.get("status") or "NOT_STARTED"
        )
        cached = identity_by_project.get(project_id)
        if cached is not None and cached[1]["identity"] is not None:
            identity = cached[1]["identity"]
        else:
            identity = _library_identity(project_id, workflow if isinstance(workflow, dict) else None)
            if cached is not None:
                cached[1]["identity"] = identity
        working_name = project.get("working_name")
        generic_name = working_name in (None, "", "AI-proposed character")
        result.append({
            "project_id": project_id,
            "completed_at": completed_at_by_project.get(project_id),
            "name": (identity["name"] if generic_name and identity["name"] else working_name) or project_id,
            "working_name": working_name,
            "title": identity["title"],
            "background": identity["background"],
            "paths": identity["paths"],
            "last_worked_at": identity["last_worked_at"] or project.get("updated_at"),
            "lifecycle": project.get("builder_lifecycle") or {},
            "build_status": build_status,
            "target_cl": identity["target_cl"],
            "current_cl": None,
            "path": ", ".join(identity["paths"]) or None,
            "updated_at": project.get("updated_at"),
            "can_export_gm": False,
            "plain_summary": (
                workflow.get("next_legal_action")
                if isinstance(workflow, dict) and workflow.get("next_legal_action")
                else "Open the character sheet to inspect this saved project."
            ),
            "workflow": workflow,
        })
    # Owner request 2026-09-13: finished characters lead by completion date
    # (newest first); characters still in progress follow by recency; every
    # abandoned draft falls to the bottom.  Name breaks ties so the order is
    # stable between identical timestamps.
    def _library_order(row: dict[str, Any]) -> tuple[int, int, str, str]:
        status = str(row.get("build_status") or "")
        stamp = str(row.get("completed_at") or row.get("last_worked_at") or row.get("updated_at") or "")
        if status == "CLEAN_AND_FINALIZED":
            tier = 0
        elif str((row.get("lifecycle") or {}).get("persistence_state") or "") == "temporary":
            tier = 1
        else:
            tier = 2
        return (tier, 0 if stamp else 1, _invert_stamp(stamp), str(row.get("name") or "").casefold())

    result.sort(key=_library_order)
    return result
