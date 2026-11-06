"""Table chooser drafts: explicit storage-only choices and scoped legal targeting.

Shared by TabletopService preview/commit, version selection and the option
manifest. Ordinary option drafts save settings on fire; an explicit version
click saves its exact augment set before aiming. Both use the same journaled
settings policy and native engine target legality.
"""
import re

from .canonical import canonical_sha256
from .ext.setting_choices import COMPOSITION_KIND, composition_spec, execute_batch
from .gate2_runtime_models import ActionIntent
from .settings_service import normalize, match_batch
from .tabletop import TabletopError


def manifest(menu, engine):
    out = {}
    if not menu or not menu.get("manual"):
        return out
    for group in menu.get("actions", []):
        action = engine.action_catalog.get(group["source_definition_id"])
        spec = composition_spec(action)
        if spec:
            for option in group["options"]:
                out[option["candidate_id"]] = {**spec, "source": action.source_definition_id,
                    "label": action.display_name}
    return out


def version_manifest(engine, actor_id):
    """Owned compiled versions, not extra combat candidates or AI offers.

    Shared by the table menu and version-click transport. The compiler's combo
    map is authoritative; hashes, labels and client-supplied augment ids are not.
    """
    from . import loadout
    actor = engine.state.actors.get(actor_id)
    out = {}
    if actor is None:
        return out
    for family, row in loadout.families(engine).get(actor_id, []):
        selected = loadout.active_action(family, row, loadout.chosen(actor, family))
        for keys, source in {"": family, **row["combos"]}.items():
            if source in actor.action_ids:
                out[source] = {"family": family, "augments": keys.split("|") if keys else [],
                               "selected": source == selected}
    return out


def select_version(table, match_id, payload, menu_read):
    """Save an exact version through composition, then offer only its targets.

    This general chooser uses the same approved clear/toggle settings as Options.
    Invalid versions or unaffordable actions never journal a selection. The
    returned state carries fresh discovery headers in place, not a full target
    menu; only the clicked source gets an exhaustive targeting pass.
    """
    session = table.combat._load_session(match_id)
    engine = session.engine
    actor_id, source = payload["actor_id"], payload["source_definition_id"]
    version = version_manifest(engine, actor_id).get(source)
    if version is None:
        actor = engine.state.actors.get(actor_id)
        action = engine.action_catalog.get(source)
        if actor is None or action is None or action.owner_id != actor_id or source not in actor.action_ids:
            raise ValueError("This fighter does not own that ability version.")
        raise ValueError("These ability improvements cannot be used together.")
    family = version["family"]
    settings = {}
    for action in engine.action_catalog.values():
        spec = composition_spec(action)
        if action.owner_id == actor_id and spec and spec["key"][:2] == ["augment", family]:
            settings[spec["key"][2]] = action.source_definition_id
    if any(key not in settings for key in [None, *version["augments"]]):
        raise ValueError("This ability version has no available improvement selection.")
    # Keep other local choices (shape, damage type, etc.), but replace this
    # family's relative augment toggles with an absolute clear + exact set.
    other = []
    for setting in payload.get("sources", []):
        action = engine.action_catalog.get(setting)
        spec = composition_spec(action)
        if not spec or spec["key"][:2] != ["augment", family]:
            other.append(setting)
    draft = {**payload, "sources": [*other, settings[None],
                                    *(settings[key] for key in version["augments"])]}
    probe, candidates = prepare(table, match_id, draft)
    if not candidates:
        from .action_legality import query
        answer = query(probe, actor_id, source)
        raise ValueError(answer.get("reason") or "No legal targets are available for this version.")
    menu = candidate_menu(table, probe, candidates, actor_id)
    match_batch(table, match_id, actor_id, draft["sources"], draft["request_id"], kind=COMPOSITION_KIND)
    read = menu_read or {}
    state = table.state(match_id, fog=bool(read.get("fog")), fog_view=read.get("fog_view"),
                        fog_actor_ids=tuple(read.get("fog_actor_ids") or ()), lazy=True)
    # Keep the other sources reachable through their fresh lazy headers, while
    # the clicked version already owns issued options (also on later polls).
    expanded = {group["source_definition_id"]: {**group, "lazy": False, "expanded_from_lazy": True}
                for group in menu["actions"]}
    if state.get("menu"):
        state["menu"]["actions"] = [{**group, **expanded.pop(group["source_definition_id"], {})}
                                    for group in state["menu"]["actions"]]
        state["menu"]["actions"].extend(expanded.values())
    return {"menu": menu, "state": state}


def nest_attack_choices(menu, engine, out):
    """TabletopService._shapes: nest opt-in hit selectors in existing attack Options.

    Plug-ins declare delivery scope through option_composition; this presentation
    seam neither invents attacks nor changes hit-time eligibility or consent.
    """
    from .attack_delivery import is_ranged

    def attacks(value):
        if isinstance(value, dict):
            if value.get("type") == "attack":
                yield value
            for child in value.values():
                yield from attacks(child)
        elif isinstance(value, list):
            for child in value:
                yield from attacks(child)

    parents = []
    for action in engine.action_catalog.values():
        p = action.parameters or {}
        typed = p.get("typed") or {}
        if typed.get("variant_of") or p.get("targeting_variant_of"):
            continue
        profiles = list(attacks(typed.get("effects") or []))
        if profiles:
            parents.append((action, profiles))
    for group in (menu or {}).get("actions", []):
        action = engine.action_catalog.get(group["source_definition_id"])
        spec = composition_spec(action)
        scope = (spec or {}).get("attacks")
        if not scope or not group.get("options"):
            continue
        actor = engine.state.actors.get(action.owner_id)
        if actor is None:
            continue
        for parent, profiles in parents:
            if parent.owner_id != action.owner_id:
                continue
            eligible = any(scope == "any"
                or scope == "unarmed" and row.get("attack_kind") == "unarmed"
                or scope == "melee" and row.get("attack_kind") in {"weapon", "unarmed"}
                    and not is_ranged(row.get("attack_kind"), parent.range_ft,
                                      (parent.parameters.get("typed") or {}).get("weapon"))
                for row in profiles)
            if not eligible:
                continue
            rows = out.setdefault(action.owner_id, [])
            entry = next((row for row in rows if row["base"] == parent.source_definition_id), None)
            if entry is None:
                entry = {"base": parent.source_definition_id, "name": parent.display_name,
                         "zone": None, "current": None, "options": [], "augments": [],
                         "choices": [], "augments_label": None, "clear_candidate": None}
                rows.append(entry)
            active = any(c.source_definition_id == action.source_definition_id
                         for c in actor.conditions.values())
            entry.setdefault("choices", []).append({"label": action.display_name, "active": active,
                "cost": "", "activation": False, "button_id": f"act:{action.source_definition_id}",
                "candidate_id": group["options"][0]["candidate_id"]})
            if active:
                entry["current"] = " · ".join(filter(None, [entry["current"], action.display_name]))
            group["shape"] = parent.source_definition_id


def prepare(table, match_id, payload):
    """Return a disposable validated setting projection, never the cached engine."""
    session = table.combat._load_session(match_id)
    engine = session.engine
    actor_id = payload["actor_id"]
    actor = engine.state.actors.get(actor_id)
    expected = f"decision:{engine.state.state_version}:{actor_id}:{engine.state.event_sequence}"
    if (actor is None or engine.state.current_actor_id != actor_id
            or payload["state_version"] != engine.state.state_version or payload["decision_id"] != expected):
        raise TabletopError("TABLETOP_STALE", "The fight changed. Choose your options again.", 409)
    if getattr(engine, "typed_control_modes", {}).get(actor_id) not in {"MANUAL", "SUGGESTED", "MANUAL_AI_BRIDGE"}:
        raise TabletopError("TABLETOP_NOT_YOUR_TURN", "Only a player-controlled fighter can compose this action.", 409)
    if table.decision_driver is not None:
        owner = (actor.owner_id if not actor.primary_combatant else None) or actor_id
        if table.decision_driver.seats(match_id).get(owner, {}).get('control') == 'MODEL':
            raise TabletopError("TABLETOP_NOT_YOUR_TURN", "This fighter is controlled by the AI.", 409)
    if table._pending_action_path(match_id).is_file():
        raise TabletopError("TABLETOP_PENDING", "Answer the open combat question first.", 409)
    sources = normalize(engine.action_catalog, actor_id, payload["sources"], COMPOSITION_KIND)
    if sources != payload["sources"]:
        raise ValueError("Choose each setting only once.")
    source = payload["source_definition_id"]
    action = engine.action_catalog.get(source)
    if action is None or action.owner_id not in (None, '*', actor_id):
        raise ValueError("Choose an ability this fighter owns.")
    binding = {"kind": COMPOSITION_KIND, "sources": sources}
    probe = table.combat._clone_engine(table.combat.source_root, engine)
    intent = ActionIntent(intent_id=f"settings:{actor_id}:{payload['request_id']}", decision_id="settings:v1",
        candidate_id=canonical_sha256(binding), actor_id=actor_id, target_ids=(actor_id,),
        state_version=engine.state.state_version)
    execute_batch(probe, intent, binding)
    from . import loadout
    family = next((row for base, row in loadout.families(probe).get(actor_id, []) if base == source), None)
    active = loadout.active_action(source, family, loadout.chosen(probe.state.actors[actor_id], source)) if family else None
    wanted = {active or source}
    # Targeting variants are legal alternatives of the selected ability, too.
    wanted.update(a.source_definition_id for a in probe.action_catalog.values()
                  if a.parameters.get("targeting_variant_of") in wanted)
    candidates = probe.action_candidates_for_sources(wanted)
    return probe, candidates


def preview(table, match_id, payload):
    engine, candidates = prepare(table, match_id, payload)
    return {"menu": candidate_menu(table, engine, candidates, payload["actor_id"])}


def candidate_menu(table, engine, candidates, actor_id):
    """Project a scoped chooser using the normal table target presentation."""
    context = {"decision_id": f"decision:{engine.state.state_version}:{actor_id}:{engine.state.event_sequence}",
               "state_version": engine.state.state_version, "active_actor_id": actor_id,
               "legal_candidates": [c.model_dump(mode="json") for c in candidates]}
    names = {a.entity_id: a.display_name for a in engine.state.actors.values()}
    definitions = {source: action.display_name for source, action in engine.action_catalog.items()}
    menu = table._menu({"context": context, "control_mode": "MANUAL"}, names, definitions, engine=engine)
    table._menu_descriptions(menu, engine)
    table._round_areas(menu, engine)
    return menu


def resolve_draft(table, match_id, payload, candidate_id, option_ids):
    """The single draft check shared by preparation and commit. Journals nothing.

    The composed candidate is not on the live menu until its settings are saved, so both callers validate the
    candidate and options on the disposable projection. Commit then saves the settings and resolves the same
    candidate on the live engine (_act_locked).
    """
    probe, candidates = prepare(table, match_id, payload)
    candidate = next((c for c in candidates if c.candidate_id == candidate_id), None)
    if candidate is None:
        raise ValueError("That target is not legal for the chosen options.")
    from .choice_authority import validate_option_selection
    if validate_option_selection(candidate, tuple(candidate.option_ids if option_ids is None else option_ids)):
        raise ValueError("Those action options are not legal together.")
    return probe, candidate


def check(table, match_id, payload, candidate_id, option_ids, after=0, reactions=None):
    """Run ordinary noncommitting preparation on the commit-validated draft."""
    probe, candidate = resolve_draft(table, match_id, payload, candidate_id, option_ids)
    intent = {key: value for key, value in candidate.model_dump(mode="json").items()
              if key in {"candidate_id", "decision_id", "state_version", "actor_id", "target_ids", "destination", "option_ids"}}
    if option_ids is not None:
        intent["option_ids"] = list(option_ids)
    return table._prepare_action(match_id, intent, after, reactions,
        engine=table.combat._load_session(match_id).engine, projected_engine=probe)


def commit(table, match_id, payload, candidate_id, after, reactions, option_ids):
    """One HTTP submission: validate the draft, journal settings, submit combat.

    The free standing settings and combat action retain separate durable journal
    transactions. A reaction cancellation can leave the selected settings saved,
    just as cancelling after choosing an option in the previous UI did.
    """
    # A continuation reuses the already journaled settings. The existing pending
    # request pins candidate, targets and answers; retry identity pins the draft.
    request_id = payload["request_id"]
    if not isinstance(request_id, str) or not re.fullmatch(r"[a-zA-Z0-9_-]{1,80}", request_id):
        raise ValueError("The option draft needs a valid request identifier.")
    session = table.combat._load_session(match_id)
    intent_id = f"settings:{payload['actor_id']}:{request_id}"
    previous = next((r for r in session.mechanical._records if r["record_type"] == "PREPARE"
                     and r["intent"]["intent_id"] == intent_id), None)
    if previous is None:
        resolve_draft(table, match_id, payload, candidate_id, option_ids)
    receipt = match_batch(table, match_id, payload["actor_id"], payload["sources"], request_id, kind=COMPOSITION_KIND)
    session = table.combat._load_session(match_id)
    engine = session.engine
    decision_id = f"decision:{engine.state.state_version}:{payload['actor_id']}:{engine.state.event_sequence}"
    return table._act_locked(match_id, candidate_id, decision_id, receipt["state_version"], after, reactions,
                     option_ids=option_ids, defer_menu=True)
