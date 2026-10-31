"""Shared selector classification for typed execution, reactions, event hooks and table buttons.

Builders opt in with parameters['setting_only'] = True for free self actions
that only store a future selection or show rules without gameplay effects.
Display names and effect names are not an
execution contract. Unflagged saved actions retain ordinary combat activity.

Shared validate_batch/execute_batch are used by Gate3 persistence and historical
compatibility re-execution. The settings_batch_key hook approves exact effects;
sheet defaults use the same approvals at match_start, before AI defaults.
"""

from typing import Any

from . import hook


def install_ai_setting_defaults(engine: Any, actor: Any = None) -> None:
    """Install opt-in sealed choices for AI owners; used by match/turn-start hooks.

    Ability builders supply the condition, source and data. Existing choices,
    manual actors and unflagged historical bundles are left alone.
    """
    modes = getattr(engine, "typed_control_modes", None)
    if modes is None:
        modes = (getattr(engine, "_roster_setup", {}) or {}).get("participant_control_modes", {})
    for action in engine.action_catalog.values():
        default = (action.parameters or {}).get("ai_setting_default")
        if not default or not is_setting_action(action):
            continue
        owner = engine.state.actors.get(action.owner_id)
        if owner is None or (actor is not None and owner.entity_id != actor.entity_id):
            continue
        controller = owner.entity_id if owner.primary_combatant else owner.owner_id or owner.entity_id
        if (modes or {}).get(controller) not in {"LOCAL_AUTO", "API_AUTO"}:
            continue
        condition = default["condition_id"]
        if any(c.condition_id == condition for c in owner.conditions.values()):
            continue
        engine._apply_condition(owner, condition, default["source_definition_id"], owner.entity_id,
                                expires_on="UNTIL_REMOVED", data=dict(default["data"]))


@hook("match_start", priority=100)
def ai_setting_defaults_at_match_start(engine: Any) -> None:
    # Recorded sheet choices run first and take precedence over AI defaults.
    install_ai_setting_defaults(engine)


@hook("turn_start")
def ai_setting_defaults_at_turn_start(engine: Any, actor: Any) -> None:
    install_ai_setting_defaults(engine, actor)


def is_setting_action(action: Any) -> bool:
    """Whether a free self action only stores a selection or shows rules."""
    if action is None:
        return False
    get = action.get if isinstance(action, dict) else lambda key, default=None: getattr(action, key, default)
    if get("economy") != "NONE" or get("target_kind") != "SELF" or get("costs"):
        return False
    parameters = get("parameters") or {}
    return parameters.get("setting_only") is True


BATCH_KIND = "SETTINGS_BATCH_V1"
COMPOSITION_KIND = "OPTION_COMPOSITION_V1"
BATCH_KINDS = {BATCH_KIND, COMPOSITION_KIND}


def composition_spec(action):
    """Explicit storage-only chooser contract, also used by the table client."""
    from . import run
    if not is_setting_action(action):
        return None
    rows = [row for row in run("option_composition", action) if row is not None]
    return rows[0] if len(rows) == 1 else None


def batch_key(action, kind=BATCH_KIND):
    from . import run
    if kind == COMPOSITION_KIND:
        spec = composition_spec(action)
        return tuple(spec["key"]) if spec else None
    keys = [key for key in run("settings_batch_key", action) if key is not None]
    return keys[0] if is_setting_action(action) and len(keys) == 1 else None


@hook("option_composition")
def area_composition(action):
    """Compiler-sealed area talents and augment toggles store choices only."""
    p = action.parameters or {}
    effects = (p.get("typed") or {}).get("effects") or []
    if len(effects) != 1:
        return None
    eff = effects[0]
    if (p.get("zone_shape") and eff.get("type") == "shape_zone"
            and eff.get("zone") == p["zone_shape"] and eff.get("talents") == p.get("shape_talents")):
        return {"key": ["shape", p["zone_shape"]], "mode": "select", "family": p.get("shape_of"),
                "costs": p.get("shape_costs") or {}}
    if (p.get("augment_toggle") and eff == {"type": "toggle_augment", "family": p["augment_toggle"], "augment": p.get("augment_key")}):
        return {"key": ["augment", p["augment_toggle"], p.get("augment_key")],
                "mode": "toggle" if p.get("augment_key") is not None else "clear", "family": p["augment_toggle"]}
    return None


@hook("match_start", priority=50)
def recorded_sheet_presets(engine):
    """Apply only newly recorded roster defaults, before AI defaults; reload replaces genesis."""
    from . import run
    from ..typed_executor import Context, run_effects
    from ..gate2_runtime_models import ActionIntent
    for actor_id, sources in (getattr(engine, "_roster_setup", {}) or {}).get("settings_presets_v1", {}).items():
        actor = engine.state.actors.get(actor_id)
        if actor is None:
            continue
        for source in sources:
            action = engine.action_catalog.get(source)
            if action is None or action.owner_id != actor_id or not is_setting_action(action):
                continue
            if len([key for key in run("settings_batch_key", action) if key is not None]) != 1:
                continue
            intent = ActionIntent(intent_id="system:sheet-presets", decision_id="settings:v1", candidate_id=source,
                                  state_version=engine.state.state_version, actor_id=actor_id)
            typed = action.parameters["typed"]
            run_effects(Context(engine, actor, action, intent, typed, [], None), typed["effects"])


def validate_batch(engine: Any, intent: Any, binding: dict) -> list[Any]:
    """Gate3/recovery seam: validate sealed, owned settings, never arbitrary free actions.

    The binding records the versioned opt-in policy and exact source definitions.
    Plug-ins explicitly approve their storage-only effects via settings_batch_key.
    Pending combat choices cannot be changed underneath an accepted preview.
    """
    from . import run
    from ..canonical import canonical_sha256
    if set(binding) != {"kind", "sources"} or binding["kind"] not in BATCH_KINDS:
        raise ValueError("Invalid settings batch policy.")
    sources = binding["sources"]
    actor = engine.state.actors.get(intent.actor_id)
    if (not isinstance(sources, list) or not 1 <= len(sources) <= 64 or actor is None
            or engine.state.terminal_result is not None or engine.state.pending_resolution is not None
            or intent.state_version != engine.state.state_version
            or intent.candidate_id != canonical_sha256(binding)
            or intent.target_ids != (intent.actor_id,) or intent.option_ids or intent.destination is not None
            or intent.movement_path is not None or intent.relation_change is not None):
        raise ValueError("These choices cannot be saved in the current fight.")
    if (intent.reaction_decisions or intent.object_ids or intent.condition_instance_id is not None
            or intent.penalty_id is not None or intent.source_effect_dc is not None or intent.movement_mode is not None
            or intent.decision_id != "settings:v1"):
        raise ValueError("Settings cannot carry combat decisions.")
    actions, keys = [], set()
    for source in sources:
        action = engine.action_catalog.get(source) if isinstance(source, str) else None
        if action is None or action.owner_id != intent.actor_id or not is_setting_action(action):
            raise ValueError("That is not a setting this character owns.")
        key = batch_key(action, binding["kind"])
        if key is None or key in keys:
            raise ValueError("That setting does not support a batch, or was selected twice.")
        keys.add(key)
        actions.append(action)
    return actions


def execute_batch(engine: Any, intent: Any, binding: dict) -> None:
    """Execute the recorded storage-only policy with one version/event transaction.

    Used only by Gate3 after durable PREPARE, and by recovery/compatibility replay.
    No candidates, combat activation, economy, technique hooks or reaction preview.
    """
    from ..typed_executor import Context, run_effects
    actions = validate_batch(engine, intent, binding)
    actor = engine.state.actors[intent.actor_id]
    with engine._transaction(actions[0].source_definition_id, intent.intent_id, actor.entity_id):
        for action in actions:
            typed = action.parameters["typed"]
            run_effects(Context(engine, actor, action, intent, typed, [], None), typed["effects"])


def setting_intent_event(engine: Any, event_type: str) -> bool:
    """INTENT_ACCEPTED for a selector is bookkeeping, not an action trigger."""
    return event_type == "INTENT_ACCEPTED" and bool(engine.events) and is_setting_action(
        engine.action_catalog.get(engine.events[-1].source_definition_id))
