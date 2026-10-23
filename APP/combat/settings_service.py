"""Compact settings transport for table/sheet; no combat preview or sheet rebuild.

Gate3 owns durable batches. Character defaults are a separate validated preference
store, applied by the existing match_start hook only when creating a new fight.
"""
import json
import re
import threading

from .canonical import canonical_sha256
from .gate2_runtime_models import ActionDefinition, ActionIntent
from .gate3_storage import atomic_write_bytes
from .ext import run
from .ext.setting_choices import BATCH_KIND, is_setting_action, batch_key


_PROJECT_LOCK = threading.RLock()


def preset_path(table, project_id):
    # Reuse the existing project-ID validation; no caller-controlled paths.
    table.buttons._path(project_id)
    return table.combat.userdata_root / "tabletop_presets" / f"{project_id}.json"


def saved_presets(table, project_id):
    path = preset_path(table, project_id)
    return json.loads(path.read_text()) if path.is_file() else {}


def sheet_rows(table, project_id, bundle, affected_sources=None):
    """Optional plug-in presentation; generic settings need no rider schema."""
    actions = {a["source_definition_id"]: ActionDefinition.model_validate(a) for a in bundle["action_catalog"]}
    saved = [source for source in saved_presets(table, project_id).values()
             if source in actions and approved_key(actions[source]) is not None]
    return [row for rows in run("settings_project_rows", actions, bundle["actor_id"], saved, affected_sources)
            for row in rows]


def batch_rows(engine, actor_id, sources):
    """Flatten optional affected modifier rows, keeping receipts schema-independent."""
    return [row for rows in run("settings_batch_rows", engine, actor_id, sources) for row in rows]


def approved_key(action):
    keys = [key for key in run("settings_batch_key", action) if key is not None]
    return keys[0] if is_setting_action(action) and len(keys) == 1 else None


def normalize(actions, actor_id, sources, kind=BATCH_KIND):
    if not isinstance(sources, list) or not 1 <= len(sources) <= 64:
        raise ValueError("Choose between one and 64 settings to save.")
    selected = {}
    for source in sources:
        action = actions.get(source)
        key = batch_key(action, kind) if action is not None and action.owner_id == actor_id else None
        if key is None:
            raise ValueError("That is not a preset this character owns.")
        selected[key] = source  # last absolute value wins
    return list(selected.values())


def changed_rows(actions, sources, kind=BATCH_KIND):
    return [{"key": list(batch_key(actions[source], kind)), "source": source,
             "button_id": f"act:{source}"} for source in sources]


def project_batch(table, project_id, sources):
    from .tabletop_service import _table_action_lock
    with _PROJECT_LOCK:
        path = preset_path(table, project_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        # Reuse the existing portable Windows/POSIX lock and bounded queue.
        # One preferences-directory lock prevents cross-process lost updates.
        with _table_action_lock(path.parent, project_id):
            _sheet, bundle, _summary = table._bundle_and_summary(project_id)
            actions = {a["source_definition_id"]: ActionDefinition.model_validate(a) for a in bundle["action_catalog"]}
            sources = normalize(actions, bundle["actor_id"], sources)
            saved = saved_presets(table, project_id)
            for source in sources:
                saved[json.dumps(approved_key(actions[source]))] = source
            atomic_write_bytes(path, json.dumps(saved, sort_keys=True).encode())
            return {"rows": changed_rows(actions, sources), "modifier_rows": sheet_rows(table, project_id, bundle, sources)}


def match_batch(table, match_id, actor_id, sources, request_id, *, kind=BATCH_KIND):
    if not re.fullmatch(r"[a-zA-Z0-9_-]{1,80}", request_id or ""):
        raise ValueError("A settings request needs a valid retry identifier.")
    # Cache only while all match inputs keep their existing service fingerprint.
    # The table lock covers validation through publication. Other writers invalidate
    # this cache, including ordinary attacks, metadata changes and journal recovery.
    cache = getattr(table, "_settings_sessions", {})
    def fingerprint_now():
        extra = []
        for path in (table.combat._metadata_path(match_id), table._pending_action_path(match_id),
                     table._match_dir(match_id) / "ControllerJournal.ndjson",
                     table._match_dir(match_id) / "Journal.ndjson"):
            extra.append((path.stat().st_size, path.stat().st_mtime_ns) if path.is_file() else None)
        return table.combat._fingerprint(match_id), tuple(extra)
    fingerprint = fingerprint_now()
    cached = cache.get(match_id)
    session = None
    if cached and cached[0] == fingerprint:
        try:
            # Reuse mechanical state only while the saved inputs are intact.
            # Current engine and policy source edits require no saved approval.
            table.combat.persistence._load_lock_genesis(cached[1].store)
        except Exception:
            cache.pop(match_id, None)
        else:
            session = cached[1]
    if session is None:
        session = table.combat._load_session(match_id)
    engine = session.engine
    sources = normalize(engine.action_catalog, actor_id, sources, kind)
    binding = {"kind": kind, "sources": sources}
    intent_id = f"settings:{actor_id}:{request_id}"
    # Retry identity is durable, not an in-memory receipt. Never replay a toggle
    # or reinterpret a request whose reply was lost after COMMIT.
    previous = next((r for r in session.mechanical._records if r["record_type"] == "PREPARE"
                     and r["intent"]["intent_id"] == intent_id), None)
    if previous:
        if previous["candidate_binding"] != binding:
            raise ValueError("That retry identifier was already used for different settings.")
        committed = any(r["record_type"] == "COMMIT" and r["transaction_id"] == previous["transaction_id"]
                        for r in session.mechanical._records)
        if committed:
            return {"rows": changed_rows(engine.action_catalog, sources, kind), "modifier_rows": batch_rows(engine, actor_id, sources),
                    "state_version": engine.state.state_version,
                    "last_sequence": engine.state.event_sequence, "request_id": request_id}
    if table._pending_action_path(match_id).is_file():
        raise ValueError("Answer the open combat question before saving these choices.")
    mode = getattr(engine, "typed_control_modes", {}).get(actor_id)
    if mode not in {"MANUAL", "SUGGESTED", "MANUAL_AI_BRIDGE"}:
        raise ValueError("Only a player-controlled character can save these choices.")
    intent = ActionIntent(intent_id=intent_id, decision_id="settings:v1", candidate_id=canonical_sha256(binding),
                          actor_id=actor_id, target_ids=(actor_id,), state_version=engine.state.state_version)
    # Validate before opening controller audit, too.
    table.combat.persistence._validate_intent_binding(engine, intent, binding)
    try:
        session.submit_intent(intent, primary_decision_record=None, reaction_provider=None, settings_binding=binding)
    except BaseException:
        cache.pop(match_id, None)
        raise
    cache[match_id] = (fingerprint_now(), session)
    while len(cache) > 8:
        cache.pop(next(iter(cache)))
    table._settings_sessions = cache
    return {"rows": changed_rows(engine.action_catalog, sources, kind), "modifier_rows": batch_rows(engine, actor_id, sources),
            "state_version": engine.state.state_version,
            "last_sequence": engine.state.event_sequence, "request_id": request_id}


def presets_for_roster(service, actor_ids):
    """Freeze project defaults in roster setup; old rosters have no new policy."""
    out = {}
    for actor_id in actor_ids:
        if not actor_id.startswith("actor:factory."):
            continue
        project = actor_id.removeprefix("actor:factory.")
        if not re.fullmatch(r"[0-9a-f-]{8,64}", project):
            continue
        path = service.userdata_root / "tabletop_presets" / f"{project}.json"
        if path.is_file():
            out[actor_id] = list(json.loads(path.read_text()).values())
    return out
