"""Shared damage-on-hit Form choices for Counter Palm, Court, Sovereign and Hundred-Form Combination.

Counter Palm, Court of One Hundred Forms, Sovereign Iron-Body and Hundred-Form Combination use this helper; only explicitly supported, owned Forms are captured
from typed authority at compilation. Old bundles without the marker are inert.
Other Forms remain printed riders until their distinct triggers are supported.
"""
from __future__ import annotations

import copy
from typing import Any

from . import effect, hook
from .needle import ask, checkpoint_id

BREAKING = "TAL_IRON_FIST_BREAKING_KNUCKLE"
RISING = "TAL_IRON_FIST_RISING_KNEE"
ELBOW = "TAL_IRON_FIST_ELBOW_IN_THE_DOOR"
COURT = "TAL_IRON_FIST_COURT_OF_ONE_HUNDRED_FORMS"
COURT_ACTIVE = "condition:typed.iron_court_forms"
COURT_USED = "iron_court_form_turn"
SOVEREIGN = "TAL_IRON_FIST_SOVEREIGN_IRON_BODY_INCARNATION"
SOVEREIGN_ACTIVE = "condition:typed.sovereign_iron_body"
SOVEREIGN_USED = "iron_sovereign_form_turn"
HUNDRED = 'TAL_IRON_FIST_HUNDRED_FORM_COMBINATION'
HUNDRED_ACTIVE = 'condition:typed.hundred_form_combination'


def court_active(actor: Any) -> bool:
    """Owned active Court marker, shared with Iron Fist's mark-producing follow-ups."""
    return any(c.condition_id == COURT_ACTIVE for c in actor.conditions.values())


@hook("maneuvers")
def compile_forms(info: dict[str, Any]) -> dict[str, Any] | None:
    """Freeze owned supported Form effects on natural actions for reactions."""
    owned = set(info["owned"])
    court = COURT in owned and any(row.get("type") == "iron_court_forms"
                                  for row in info["mechanics"][COURT].get("effects") or [])
    sovereign = SOVEREIGN in owned and any(row.get("type") == "iron_fist_rider" and row.get("kind") == "sovereign_forms"
                                          for row in info["mechanics"][SOVEREIGN].get("effects") or [])
    hundred = HUNDRED in owned and any(row.get('type') == 'iron_fist_rider' and row.get('kind') == 'hundred_forms'
                                      for row in info['mechanics'][HUNDRED].get('effects') or [])
    if "TAL_IRON_FIST_COUNTER_PALM" not in owned and not court and not sovereign and not hundred:
        return None
    forms = []
    for key in (BREAKING, RISING, ELBOW):
        if key not in owned:
            continue
        mechanic = info["mechanics"].get(key) or {}
        effects = copy.deepcopy((mechanic.get("modifier") or {}).get("effects") or [])
        if key == BREAKING:
            # The printed expiry belongs to the striker, not the current turn.
            for row in effects:
                if row.get("type") == "if_marked":
                    for nested in row.get("effects") or []:
                        nested["duration"] = "until_end_of_your_next_turn"
        forms.append({"id": key, "name": mechanic["name"], "effects": effects})
    for action in info["actions"]:
        if ".natural." in action.source_definition_id and "#" not in action.source_definition_id:
            action.parameters["iron_forms"] = forms
    return None


def strike_damaged(ctx: Any, target: Any) -> bool:
    """Actual strike damage, shared by reaction choices and terrain Forms."""
    damaged = False
    for event in reversed(ctx.engine.events):
        if event.event_type == "ATTACK_ROLLED" and event.actor_id == ctx.actor.entity_id:
            break
        if event.event_type == "DAMAGE_COMMITTED" and event.source_definition_id == ctx.source \
                and event.actor_id == ctx.actor.entity_id and target.entity_id in event.target_ids:
            payload = event.payload or {}
            damaged |= int(payload.get("hp_damage") or 0) + int(payload.get("temporary_hp_absorbed") or 0) > 0
    return damaged


@hook("attack_mode")
def reset_forms(ctx: Any, target: Any) -> None:
    """Start the per-strike ledger before any hit follow-up can place a mark."""
    if any(action.parameters.get("iron_forms") for action in ctx.engine.action_catalog.values()
           if action.owner_id == ctx.actor.entity_id):
        ctx.damage_cache["iron_forms_applied"] = []


def apply_form(ctx: Any, target: Any, *, prompt: str | None = None, extra: bool = False,
               form_ids: set[str] | None = None) -> bool:
    """Choose at most one owned, eligible damage-on-hit Form; declining is free."""
    from ..typed_executor import run_effects, _walk_rows

    if not strike_damaged(ctx, target):
        return False
    forms = next((action.parameters["iron_forms"] for action in ctx.engine.action_catalog.values()
                  if action.owner_id == ctx.actor.entity_id and "iron_forms" in action.parameters), [])
    grappling = any(c.condition_id.endswith(".grappled") and c.source_actor_id == other.entity_id
                    for subject, other in ((ctx.actor, target), (target, ctx.actor))
                    for c in subject.conditions.values())
    from .iron_elbow import shared_spaces

    applied = ctx.damage_cache.setdefault("iron_forms_applied", [])
    # Ordinary strikes already carry their normal Form rows, which execute later
    # than Opening. Do not apply those again through Court's extra choice.
    scheduled = {row.get("source_modifier") for row in _walk_rows(ctx.typed.get("effects") or [])} if extra else set()
    eligible = {row["id"]: row for row in forms
                if row["id"] not in applied and row["id"] not in scheduled
                and (form_ids is None or row['id'] in form_ids)
                and (row["id"] != RISING or grappling)
                and (row["id"] != ELBOW or ctx.engine._distance_actor_to_actor(ctx.actor, target) <= 5
                     and shared_spaces(ctx.engine, ctx.actor, target))}
    if not eligible:
        return False
    selected = ask(ctx.engine, ctx.intent,
                   checkpoint_id(ctx.engine, "Form on hit", ctx.actor.entity_id, target.entity_id), ctx.actor,
                   "choice:needle.iron_forms", list(eligible),
                   labels={key: row["name"] for key, row in eligible.items()}, allow_decline=True,
                   target_id=target.entity_id,
                   prompt=prompt or f"{ctx.action.display_name} hits {target.display_name}: choose one Form or decline")
    if len(selected) == 1 and selected[0] in eligible:
        applied.append(selected[0])
        run_effects(ctx, eligible[selected[0]]["effects"])
        return True
    return False


@effect("iron_court_forms")
def court_forms(ctx: Any, row: dict[str, Any]) -> None:
    """Persist active Court eligibility for its printed duration and early ending."""
    from ..typed_executor import effect_expiry

    ctx.engine._remove_condition(ctx.actor, COURT_ACTIVE, ctx.source)
    ctx.engine._apply_condition(ctx.actor, COURT_ACTIVE, ctx.source, ctx.actor.entity_id,
                                expires_on=effect_expiry(ctx, row, ctx.actor, condition=True),
                                data={"dodge_strike": 1} if row.get("dodge_strike") else {})


@hook("resolution_final")
def court_dodge_strike(engine: Any, actor: Any, action: Any, candidate: Any, intent: Any) -> None:
    """One native Unarmed Strike inside Dodge, before action-completed responses.

    New reviewed Court activations opt in with a persisted integer capability;
    old bundles/saved markers remain inert. Dodge cannot itself end combat, so
    this uses the ordinary nonterminal attack path, not post-terminal attacks.
    """
    from ..recipients import allowed
    from ..typed_executor import Context, run_effects
    from .needle import incapacitated

    if action.source_definition_id != "system:combat.dodge" or not actor.active or incapacitated(actor):
        return
    if engine.state.terminal_result is not None or not any(
            c.condition_id == COURT_ACTIVE and c.source_actor_id == actor.entity_id
            and c.data.get("dodge_strike") == 1 for c in actor.conditions.values()):
        return
    natural = next((a for a in engine.action_catalog.values()
                    if a.owner_id == actor.entity_id and ".natural." in a.source_definition_id
                    and "#" not in a.source_definition_id
                    and any(e.get("type") == "attack" and e.get("attack_kind") == "unarmed"
                            for e in (a.parameters.get("typed") or {}).get("effects") or [])), None)
    if natural is None:
        return
    # Resolve Court together with every other active reach row through the
    # shared helper; never invent a parallel reach calculation here.
    from .reach_bonus import current_reach
    natural = natural.model_copy(update={"range_ft": current_reach(engine, actor, natural)})
    targets = {other.entity_id: other for other in engine.state.actors.values()
               if allowed(engine, actor, other, natural)}
    picked = ask(engine, intent, checkpoint_id(engine, "Court Dodge strike", actor.entity_id), actor,
                 "choice:needle.iron_court_dodge", list(targets), allow_decline=True,
                 labels={key: f"Unarmed Strike against {other.display_name} (no additional cost)"
                         for key, other in targets.items()}, name="Court of One Hundred Forms", feature_id=COURT,
                 prompt=f"Court of One Hundred Forms: {actor.display_name} takes Dodge. Choose a creature "
                        "for one Unarmed Strike before Dodge finishes; no additional action, Reaction, "
                        "Martial Focus or Stamina cost.")
    if not picked:
        return
    target = targets[picked[0]]
    if not allowed(engine, actor, target, natural):
        return
    typed = copy.deepcopy(natural.parameters["typed"])
    # This is one strike, not the Attack action: Extra Attack and Flurry's
    # Attack-action prerequisite must not turn Dodge into an attack sequence.
    typed["attack_action"] = False
    for row in typed["effects"]:
        if row.get("type") == "attack":
            row["count"] = 1
            row.pop("count_by_cl", None)
    run_effects(Context(engine, actor, natural, intent, typed, [target], target), typed["effects"])


@hook("mark_applied")
def court_form(ctx: Any, name: str, target: Any) -> None:
    """One additional eligible Form per actual turn; normal Form limits stay intact.

    The supported Forms require damaging an Unarmed Strike target. Other Open
    triggers and unsupported Forms remain riders, rather than bypassing their rules.
    """
    if name.lower() != "opened" or not court_active(ctx.actor):
        return
    if ".natural." not in ctx.source and not any(row.get("type") == "attack" and row.get("attack_kind") == "unarmed"
                                                for row in ctx.typed.get("effects") or []):
        return
    current = ctx.engine.state.actors.get(ctx.engine.state.current_actor_id or "")
    if current is None:
        return
    stamp = f"{ctx.engine.state.round_number}:{current.entity_id}:{current.turns_started}"
    if ctx.actor.turn_flags.get(COURT_USED) == stamp:
        return
    # Reserve before resolving nested effects, so any mark follow-up cannot recurse.
    prior = ctx.actor.turn_flags.get(COURT_USED)
    ctx.actor.turn_flags[COURT_USED] = stamp
    if not apply_form(ctx, target, extra=True, prompt=f"Court of One Hundred Forms after {ctx.action.display_name} Opens {target.display_name}: choose one extra Form or decline"):
        if prior is None:
            ctx.actor.turn_flags.pop(COURT_USED, None)
        else:
            ctx.actor.turn_flags[COURT_USED] = prior


@effect("iron_form_on_hit")
def form_on_hit(ctx: Any, row: dict[str, Any]) -> None:
    if ctx.target is not None:
        apply_form(ctx, ctx.target)


@hook("after_hit_choice")
def sovereign_form(ctx: Any, target: Any, kind: str) -> None:
    """One extra supported Form per actual turn, including off-turn Unarmed hits.

    The shared Form ledger excludes the ordinary Form and Court's Form on this
    strike. Declining or having no eligible Form never consumes Sovereign's use.
    Other Form triggers remain riders; this hook does not bypass their prerequisites.
    """
    from .iron_fist_riders import config
    from .needle import incapacitated

    if kind != "unarmed" or "sovereign_forms" not in config(ctx.engine, ctx.actor):
        return
    if not ctx.actor.active or incapacitated(ctx.actor) or not any(
            c.condition_id == SOVEREIGN_ACTIVE and c.source_actor_id == ctx.actor.entity_id
            for c in ctx.actor.conditions.values()):
        return
    current = ctx.engine.state.actors.get(ctx.engine.state.current_actor_id or "")
    if current is None:
        return
    stamp = f"{ctx.engine.state.round_number}:{current.entity_id}:{current.turns_started}"
    if ctx.actor.turn_flags.get(SOVEREIGN_USED) == stamp:
        return
    # Reserve before nested effects can produce further hit/mark follow-ups.
    prior = ctx.actor.turn_flags.get(SOVEREIGN_USED)
    ctx.actor.turn_flags[SOVEREIGN_USED] = stamp
    if not apply_form(ctx, target, extra=True,
                      prompt=f"Sovereign Iron-Body Incarnation after {ctx.action.display_name} hits {target.display_name}: choose one extra Form or decline"):
        if prior is None:
            ctx.actor.turn_flags.pop(SOVEREIGN_USED, None)
        else:
            ctx.actor.turn_flags[SOVEREIGN_USED] = prior


@hook('attack_result')
def hundred_form_selection(ctx, target, hit, critical):
    """Two actual Unarmed Strikes in this Attack action unlock the two Forms."""
    from ..gate2_runtime_models import EconomyKind
    from .iron_fist_riders import config
    from .effect_durations import token
    if ('hundred_forms' not in config(ctx.engine, ctx.actor) or not ctx.actor.active
            or ctx.engine.state.terminal_result is not None or not ctx.typed.get('attack_action')
            or ctx.action.economy != EconomyKind.ACTION or ctx.typed.get('reaction_attack')
            or ctx.engine.state.current_actor_id != ctx.actor.entity_id
            or (ctx.attack_effect or {}).get('attack_kind') != 'unarmed'):
        return
    # Damage has already resolved. A completed strike still counts when its
    # recipient was defeated; the terminal/owner guards above govern selection.
    count = int(ctx.damage_cache.get('_hundred_strikes', 0)) + 1
    ctx.damage_cache['_hundred_strikes'] = count
    if count != 2:
        return
    forms = next((a.parameters['iron_forms'] for a in ctx.engine.action_catalog.values()
                  if a.owner_id == ctx.actor.entity_id and a.parameters.get('iron_forms')), [])
    if len(forms) < 2:
        return
    chosen = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, 'hundred_forms', ctx.actor.entity_id),
                 ctx.actor, 'choice:needle.hundred_forms', [row['id'] for row in forms], minimum=2, maximum=2,
                 allow_decline=True, labels={row['id']: row['name'] for row in forms},
                 name='Hundred-Form Combination', target_id=target.entity_id,
                 prompt=f'Hundred-Form Combination: {ctx.action.display_name} made two Unarmed Strikes. Choose two different known Forms to use once each before this turn ends, or decline. No extra cost.')
    if len(chosen) == 2:
        ctx.engine._remove_condition(ctx.actor, HUNDRED_ACTIVE, ctx.source)
        ctx.engine._apply_condition(ctx.actor, HUNDRED_ACTIVE, ctx.source, ctx.actor.entity_id,
            expires_on=token('end', ctx.actor.entity_id, ctx.actor.turns_started),
            data={'label': 'Hundred-Form Combination: two extra Forms remaining this turn', 'forms': chosen, 'used': []})


@hook('after_hit_choice')
def hundred_form_use(ctx, target, kind):
    """Each selected extra Form is used once; share the per-strike exclusion ledger."""
    from .condition_ownership import remove_instance
    from .iron_fist_riders import config
    if kind != 'unarmed' or not target.active or 'hundred_forms' not in config(ctx.engine, ctx.actor):
        return
    for _ in range(2):
        held = next((c for c in ctx.actor.conditions.values() if c.condition_id == HUNDRED_ACTIVE
                     and c.source_actor_id == ctx.actor.entity_id), None)
        if held is None or ctx.engine.state.current_actor_id != ctx.actor.entity_id:
            return
        unused = set(held.data['forms']) - set(held.data['used'])
        if not unused or not apply_form(ctx, target, extra=True, form_ids=unused,
                prompt=f'Hundred-Form Combination after {ctx.action.display_name} damages {target.display_name}: choose one unused extra Form or decline. Each can be used once this turn; the same Form cannot repeat on this strike.'):
            return
        chosen = ctx.damage_cache['iron_forms_applied'][-1]
        used = [*held.data['used'], chosen]
        remaining = len(held.data['forms']) - len(used)
        data = {**held.data, 'used': used,
                'label': f'Hundred-Form Combination: {remaining} extra Form uses remaining this turn'}
        remove_instance(ctx.engine, ctx.actor, held.instance_id, ctx.source)
        ctx.engine._apply_condition(ctx.actor, HUNDRED_ACTIVE, held.source_definition_id, ctx.actor.entity_id,
                                   expires_on=held.expires_on, data=data)
