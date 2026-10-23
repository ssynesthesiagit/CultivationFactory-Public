"""Table chooser drafts: explicit storage-only choices and scoped legal targeting.

Used by TabletopService preview/commit and the option manifest. No UI click
mutates a fight; settings are journaled once when the player submits the attack.
The engine, including its ordinary action vetoes, decides all target legality.
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
    actor_id = payload["actor_id"]
    context = {"decision_id": f"decision:{engine.state.state_version}:{actor_id}:{engine.state.event_sequence}",
               "state_version": engine.state.state_version, "active_actor_id": actor_id,
               "legal_candidates": [c.model_dump(mode="json") for c in candidates]}
    names = {a.entity_id: a.display_name for a in engine.state.actors.values()}
    definitions = {source: action.display_name for source, action in engine.action_catalog.items()}
    menu = table._menu({"context": context, "control_mode": "MANUAL"}, names, definitions, engine=engine)
    table._menu_descriptions(menu, engine)
    table._round_areas(menu, engine)
    return {"menu": menu}


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
