"""Athletics sphere automation (lane AUTO8; reviewed typing in authority/typed_mechanics/reviewed_final.d/auto8-athletics.json
and the passive rows in combat/rules/feature_blocks.d/auto8-athletics.json).

Every rule this module owns is printed in the owner's Sphere Compendium and read from
``authority/typed_mechanics/rules_text.json``; nothing here is keyed on an ability id inside a core engine file, and no hook
fires for a creature that does not own the row it checks, or does not hold the condition the clause needs.

Terrain Glide uses the public material-traversal query and route law; Multiple Motions binds its paid choices through
the public movement-sequence scope. Deliberately NOT automated here: general Shark Swim movement outside the mapped
Terrain Glide media. Rope Swing Adept's rope routing and standalone Wall Stunt
remain map-shaped text; Air Stunt with its owned Wall Stunt prerequisite now uses native provisional-wall routes. There is no breath
clock, so Strong Lungs' breath-holding multiplier stays text; Athletic Training is character creation.
Body Beyond Distance is owned by athletics_travel's elapsed-time journey.
Polearm Vaulter offers +10-foot horizontal or +5-foot vertical native vaults with an independent movement credit.
Court of Ten Thousand Steps moved here from the retired combat/ext/bodyb_motion.py so one
module owns the whole talent; its stance condition id, its +20 feet Speed and its 1-minute clock are unchanged, and every
clause is read from that persisted stance, so a fight stored before these rows existed keeps the Speed, the free stand and
the terrain clause it was always given.

Ownership and shared helpers (consumers: this module, the Athletics regression tests, and the
``athletics`` rows themselves):

  owns(engine, actor, kind)    -> bool: this fighter has that Athletics passive row.
  focus_held(actor)            -> int: Martial Focus currently held (spending is not an Action).
  turn_moved_ft(engine, actor) -> int: this turn's own willing movement (combat.ext.hold_still.moved_ft, the one
                                  implementation; teleports count as the ground they cross, forced displacement does not).
  _moved_ft_this_turn(...)     -> that plus the route in progress (combat.movement_steps.context), so one
                                  uninterrupted 20-foot route reads as 20 feet at its own checkpoints.
  used_this_turn / mark_turn_use / spent_this_turn -> the once-per-turn flags, stored as strings (a turn stamp, so a
                                  saved fight reloads them unchanged and nothing rests the rest of the fight by accident).
  _drop_condition(...)         -> remove exactly one condition instance (combat/gate2_engine._remove_condition
                                  removes every instance of an id, which would end another creature's hold too).

Shared beyond this module: combat/flight.py ``jump_score`` reads the two documented jump hooks (``jump_ability``,
``jump_bonus_ft``) this module answers for Mighty Conditioning, Polearm Vaulter and Flowing Pursuit. The "+N Armor Class
against one named creature" it applies for Flowing Pursuit is the ``condition:typed.ac_against`` shape
combat/ext/nine_star.py owns (its ``ac_against`` effect and its generic ``hit_response`` reader); no second Armor Class
reader is registered here.

Walkable roofs add a narrow ``climbing`` provider: Spider's Touch grants Climb Speed equal to land Speed, Sure Grip
grants Advantage on the native climbing Athletics check, and Mighty Conditioning offers Strength/Dexterity for that
check through its recorded choice. Spider's Touch with Sure Grip also uses ceiling grips while keeping a hand free.
Sure Grip's catch reaction remains outside this provider.
"""

from __future__ import annotations

from ..paid_relocation import activation

from typing import Any

from . import effect, hook, needle, note
from .hold_still import moved_ft as turn_moved_ft
from .needle import ask, checkpoint_id

BLOCK = "athletics"
FOCUS = "resource:core.martial_focus"
COORDINATED = "ATHLETICS_BASE_COORDINATED_MOVEMENT"
CHOICE_PREFIX = "choice:needle.athletics."

# Public test commentary omitted.
# Public test commentary omitted.
KINDS = (
    "moving_target", "court_of_steps", "heaven_treading", "sparrows_path", "powerful_wings",
    "helicopter_descent", "flash_step", "speed_boost", "dizzying_tumble",
    "meridian_threading", "flowing_pursuit", "one_breath", "polearm_vaulter", "mighty_conditioning",
    "capoeira_spin", "sudden_flank", "whirlwind_flip", "spider_touch", "air_stunt",
    "multiple_motions", "terrain_glide", "close_quarters",
)

# Public test commentary omitted.
# Public test commentary omitted.
CLOSE_QUARTERS = "TAL_ATHLETICS_CLOSE_QUARTERS_TRAINING"
CLOSE_SHARED = "condition:typed.close_quarters_shared"


def close_contact(engine, left, right):
    """A live, successfully entered shared space; preserved across a truce."""
    return any(
        owns(engine, actor, "close_quarters") and any(
            c.condition_id == CLOSE_SHARED and c.data.get("target_id") == other.entity_id
            for c in actor.conditions.values()) for actor, other in ((left, right), (right, left))) and bool(
                set(engine._actor_volume(left)) & set(engine._actor_volume(right)))


def close_hostile_contact(engine, left, right):
    """Combat benefits require current hostility; occupancy keeps its permission."""
    from ..relations import relation, ENEMY
    return relation(engine, left, right) == ENEMY and close_contact(engine, left, right)


@hook("shared_space")
def close_sharing(engine, left, right):
    return True if close_contact(engine, left, right) else None


@hook("pass_through")
def close_passage(engine, mover, occupant):
    from ..relations import relation, ENEMY
    from ..target_knowledge import knowledge
    if not owns(engine, mover, "close_quarters") or relation(engine, mover, occupant) != ENEMY:
        return
    known = knowledge(engine, mover, occupant)
    if known and known.mode == "DIRECT":
        return "difficult"


@hook("pass_through_stop")
def close_endpoint(engine, mover, occupant):
    return True if close_passage(engine, mover, occupant) else None


@hook("choice_reactors")
def close_defenders(engine):
    if not any(owns(engine, actor, "close_quarters") for actor in engine.state.actors.values()):
        return ()
    from ..tabletop_service import MANUAL_MODES
    return tuple(who for who, mode in (getattr(engine, "typed_control_modes", {}) or {}).items()
                 if mode in MANUAL_MODES)


@hook("movement_attempt")
def close_entry(engine, mover, previous, nxt, intent):
    if not owns(engine, mover, "close_quarters"):
        return
    from ..typed_executor import Context, resolve_opposed_check
    from ..gate2_runtime_models import ActionDefinition, EconomyKind
    from ..ability_checks import skill_bonus, ability_modifier
    from ..typed_reactions import opportunity_attack, opportunity_permitted_against, opportunity_profile, can_use_reaction, open_reaction
    for other in sorted(engine.state.actors.values(), key=lambda a: a.entity_id):
        if (other.entity_id == mover.entity_id or not other.active or not close_passage(engine, mover, other)
                or not set(engine._actor_volume(other)) & set(engine._actor_volume(mover, nxt))
                or set(engine._actor_volume(other)) & set(engine._actor_volume(mover, previous))):
            continue
        options = {"athletics": {"ability": "STR", "skill": "Athletics"},
                   "acrobatics": {"ability": "DEX", "skill": "Acrobatics"}}
        def bonus(key):
            row = options[key]
            return skill_bonus(engine, other, row["skill"], ability_modifier(other, row["ability"],
                numbers=needle.numbers_of(engine, other), fallback=(other.dexterity_score-10)//2 if key == "acrobatics" else None))
        chosen = ask(engine, intent, checkpoint_id(engine, "close-entry", other.entity_id), other,
            "choice:needle.athletics.close_defense", list(options),
            labels={"athletics": "Strength (Athletics)", "acrobatics": "Dexterity (Acrobatics)"},
            preferred=[max(options, key=bonus)], name="Close Quarters Training", feature_id=CLOSE_QUARTERS,
            target_id=mover.entity_id,
            prompt=f"Close Quarters Training: {mover.display_name} tries to enter {other.display_name}'s space. Choose your defending skill; no Action cost.")
        action = ActionDefinition(source_definition_id=CLOSE_QUARTERS, display_name="Close Quarters Training entry",
            owner_id=mover.entity_id, economy=EconomyKind.NONE, resolution_kind="TYPED", target_kind="SELF")
        ctx = Context(engine, mover, action, intent, {"source": CLOSE_QUARTERS,
            "numbers": needle.numbers_of(engine, mover)}, [other], other)
        result = resolve_opposed_check(ctx, other, {"ability": "DEX", "skill": "Acrobatics"}, options[chosen[0]])
        if not result.success:
            row, _, reach = opportunity_profile(engine, other)
            if (row and can_use_reaction(engine, other, mover, row)
                    and engine._distance_actor_to_actor(other, mover) <= reach
                    and opportunity_permitted_against(engine, other, mover)):
                use = ask(engine, intent, checkpoint_id(engine, "close-failed-entry", other.entity_id), other,
                    "choice:needle.athletics.close_opportunity", ["use"], labels={"use": "Make an opportunity attack (Reaction)"},
                    name="Close Quarters Training", feature_id=CLOSE_QUARTERS, target_id=mover.entity_id,
                    allow_decline=True, prompt=f"Close Quarters Training: {mover.display_name} failed to enter {other.display_name}'s space. Make an opportunity attack against {mover.display_name}, costing your Reaction?")
                if use:
                    open_reaction(engine, row, other, (mover.entity_id,), "CLOSE_QUARTERS_FAILED_ENTRY")
                    opportunity_attack(engine, other, mover, intent, reaction_opened=True)
            return {"stop": True, "source_id": CLOSE_QUARTERS,
                    "label": f"Close Quarters Training: entry failed; {mover.display_name} stops in the previous space."}


@hook("pass_through_entered")
def close_entry_recorded(engine, mover, other, intent):
    # Public test commentary omitted.
    # Public test commentary omitted.
    if close_passage(engine, mover, other):
        engine._apply_condition(mover, CLOSE_SHARED, CLOSE_QUARTERS, mover.entity_id, expires_on=None,
            data={"target_id": other.entity_id, "label": f"Close Quarters Training: sharing {other.display_name}'s space until separated"})


@hook("event")
def close_separation(engine, event_type, kwargs):
    if event_type not in {"MOVEMENT_COMMITTED", "TURN_STARTED"} or not hasattr(engine, "state"):
        return
    for actor in engine.state.actors.values():
        for c in list(actor.conditions.values()):
            if c.condition_id != CLOSE_SHARED:
                continue
            other = engine.state.actors.get(c.data.get("target_id"))
            if other is None or not other.active or not set(engine._actor_volume(actor)) & set(engine._actor_volume(other)):
                _drop_condition(engine, actor, c.instance_id, CLOSE_QUARTERS)


def close_cover_contacts(engine, attacker, target):
    """Return each outside-space cover supplier and its printed bonus."""
    if getattr(engine, "_close_cover_suppressed", False):
        return []
    from ..read_queries import shared_query
    # Public test commentary omitted.
    # Public test commentary omitted.
    # Public test commentary omitted.
    links = shared_query(engine, ('athletics.close_quarters_links',), lambda: tuple(
        (actor.entity_id, str(c.data.get('target_id')))
        for actor in engine.state.actors.values()
        for c in actor.conditions.values() if c.condition_id == CLOSE_SHARED))
    if not links:
        return []
    sizes = ("Tiny", "Small", "Medium", "Large", "Huge", "Gargantuan")
    covers = []
    for other in engine.state.actors.values():
        if other.entity_id == target.entity_id or not other.active or not close_hostile_contact(engine, target, other):
            continue
        if set(engine._actor_volume(attacker)) & (set(engine._actor_volume(target)) | set(engine._actor_volume(other))):
            continue
        a, b = (sizes.index(actor.transformed_size_category or actor.size_category) for actor in (target, other))
        covers.append((other, 2 if a == b else 5 if a < b else 0))
    return covers


@hook("directional_cover")
def close_cover(engine, attacker, target, context):
    covers = close_cover_contacts(engine, attacker, target)
    return max(bonus for _, bonus in covers) if covers else None


@hook("cover_miss_recipient")
def close_transfer(engine, attacker, target, spec, roll, intent, total, cover):
    own_cover = close_cover(engine, attacker, target, {})
    # Public test commentary omitted.
    if not own_cover or cover != own_cover:
        return
    # Public test commentary omitted.
    # Public test commentary omitted.
    prior = getattr(engine, "_close_cover_suppressed", False)
    engine._close_cover_suppressed = True
    try:
        _, other_ac = engine._attack_defense(attacker, target, spec, spec.get("source_definition_id"))
    finally:
        engine._close_cover_suppressed = prior
    if total < other_ac:
        return
    options = [other for other, bonus in close_cover_contacts(engine, attacker, target)
               if bonus == own_cover]
    return min(options, key=lambda a: a.entity_id).entity_id if options else None


@hook("attack_resolution_scope")
def close_attack_scope(engine, actor, target, spec, intent):
    if not owns(engine, actor, "close_quarters"):
        return
    from contextlib import contextmanager
    @contextmanager
    def scope():
        old = getattr(engine, "_close_attack_spec", None)
        engine._close_attack_spec = spec
        try:
            yield
        finally:
            engine._close_attack_spec = old
    return scope()


@hook("attack_mode_contribution")
def close_attack_penalty(engine, attacker, target):
    if not owns(engine, attacker, "close_quarters") or not any(
            other.entity_id != attacker.entity_id and other.active and close_hostile_contact(engine, attacker, other)
            for other in engine.state.actors.values()):
        return
    spec = getattr(engine, "_close_attack_spec", None) or {}
    from .attack_scope import current
    frame = current(engine)
    effect_row = frame["effect"] if frame and frame["actor_id"] == attacker.entity_id else (spec.get("checkpoint_context") or {}).get("effect") or {}
    action = engine.action_catalog.get(spec.get("source_definition_id"))
    typed = (action.parameters.get("typed") or {}) if action else {}
    if frame and frame["actor_id"] == attacker.entity_id:
        typed = frame["context"].typed
    weapon = typed.get("weapon") or {}
    kind = effect_row.get("attack_kind") or (action.parameters.get("attack_kind") if action else None)
    import re
    if kind in {"unarmed", "natural", "natural_weapon"} or weapon.get("natural") or re.search(r"\blight\b", str(weapon.get("properties") or ""), re.I):
        return
    return "DISADVANTAGE"
# Public test commentary omitted.
MOTION_KINDS = ("speed_bonus", "ignore_difficult", "oa_disadvantage", "afterimage", "regain_focus")


@hook("journey_step")
def journey_difficult_terrain(session, actor_id, previous, destination, regions):
    """Use the same compiled motion ownership/Focus gate outside combat."""
    from ..motion import resource_motion_rows

    actor = session.state['actors'][actor_id]
    rows = resource_motion_rows(actor['bundle'].get('typed_passives', ()),
                                actor['resources'], 'ignore_difficult')
    # Public test commentary omitted.
    # Public test commentary omitted.
    rows = [row for row in rows
            if row.get('feature_id') == 'TAL_ATHLETICS_UNIMPEDED_POSITIONING']
    if rows:
        return {'ignore_nonmagical_difficult': True}
    return None


AFTERIMAGE_TALENT = "TAL_ATHLETICS_AFTERIMAGE"
AFTERIMAGE_CONDITION = "condition:typed.afterimage"


def afterimage_row(engine, actor):
    """Compiled Athletics motion ownership, shared by progress and admission."""
    return next((row for row in engine.typed_passive_rows.get(actor.entity_id, ())
                 if row.get("block") == "motion" and row.get("kind") == "afterimage"
                 and row.get("feature_id") == AFTERIMAGE_TALENT), None)


@hook("movement_progress_committed")
def afterimage_progress(engine, mover, receipt):
    """Leave one image at the first selected own-turn crossing above 20 feet.

    Progress and creation use separate integer turn flags, cleared by native
    turn start. Destruction does not reopen this turn's threshold crossing.
    """
    row = afterimage_row(engine, mover)
    if (row is None or receipt.get("actor_id") != mover.entity_id
            or not receipt.get("voluntary") or not receipt.get("own_turn")):
        return
    from ..movement_sequences import enabled
    if not enabled(engine, mover, AFTERIMAGE_TALENT):
        return
    feet = int(receipt.get("distance_ft") or 0)
    if feet <= 0:
        return
    total = int(mover.turn_flags.get("athletics_afterimage_distance_ft") or 0) + feet
    mover.turn_flags["athletics_afterimage_distance_ft"] = total
    if total <= int(row.get("min_ft") or 20) or mover.turn_flags.get("athletics_afterimage_created"):
        return
    mover.turn_flags["athletics_afterimage_created"] = 1
    if not any(c.condition_id == AFTERIMAGE_CONDITION for c in mover.conditions.values()):
        engine._apply_condition(mover, AFTERIMAGE_CONDITION, "passive:" + AFTERIMAGE_TALENT, mover.entity_id,
                                expires_on="START_OF_SOURCE_NEXT_TURN", data={"label": "Afterimage"})


@hook("condition_application_attempt")
def afterimage_turn_admission(engine, target, condition_id, source_id, source_actor_id):
    """The Athletics motion image can only be newly created on its owner's turn.

    Match the compiled motion row and its exact passive source. Other image
    sources and already present conditions are outside this admission check.
    """
    if (condition_id != AFTERIMAGE_CONDITION
            or source_id != "passive:" + AFTERIMAGE_TALENT
            or source_actor_id != target.entity_id):
        return None
    if afterimage_row(engine, target) is not None and engine.state.current_actor_id != target.entity_id:
        return False
    return None

# Public test commentary omitted.
# Public test commentary omitted.
MOTIONS = {f'TAL_ATHLETICS_{key}': name for key, name in (
    ('AFTERIMAGE', 'Afterimage'), ('DIZZYING_TUMBLE', 'Dizzying Tumble'),
    ('FLASH_STEP', 'Flash Step'), ('FLOWING_PURSUIT', 'Flowing Pursuit'),
    ('MOBILITY', 'Mobility'), ('MOVING_TARGET', 'Moving Target'),
    ('SUDDEN_FLANK', 'Sudden Flank'), ('UNBROKEN_PURSUIT', 'Unbroken Pursuit'))}
MULTIPLE = 'TAL_ATHLETICS_MULTIPLE_MOTIONS'
GLIDE = 'TAL_ATHLETICS_TERRAIN_GLIDE'
MOTION_LABELS = dict(zip(MOTIONS, (
    'Afterimage: after moving more than 20 feet this turn, leave a decoy until your next turn',
    'Dizzying Tumble: spend 10 feet when leaving an enemy; Wisdom save or its attacks have Disadvantage until your next turn ends',
    'Flash Step: Dash and expend Martial Focus to teleport to a visible, legal destination',
    'Flowing Pursuit: move 20 feet toward a creature, then choose protection against it or a jump bonus',
    'Mobility: Opportunity Attacks for leaving a creature’s reach have Disadvantage',
    'Moving Target: move more than 20 feet this turn for Half Cover against ranged attacks until your next turn',
    'Sudden Flank: Tumble through an enemy for Advantage on your next attack against it this turn',
    'Unbroken Pursuit: spend a Reaction and Martial Focus to follow a moving creature up to half your Speed',
)))


@hook('compile_passives')
def motion_options(passives, info):
    known = [key for key in MOTIONS if key in info['owned_ids']]
    rows = [{**row, 'motions': known} if row.get('kind') == 'multiple_motions'
            and row.get('block') == BLOCK else row for row in passives]
    # Public test commentary omitted.
    # Public test commentary omitted.
    if known and MULTIPLE not in info['owned_ids']:
        rows.append({'block': BLOCK, 'kind': 'motion_composition',
                     'feature_id': known[0], 'motions': known})
    return rows


@hook('movement_begin')
def compose_motions(engine, actor, candidate, intent, granted_ft):
    from ..movement_sequences import context
    feature_id = context(engine, actor).get('feature_id')
    required = [feature_id] if feature_id in MOTIONS else []
    compose_motion_sequence(engine, actor, candidate.destination, intent, required=required)


@hook('teleport_begin')
def compose_teleport_motions(ctx, actor, previous, destination, movement_context,
                            unwilling, forced, feature_id):
    if (actor.entity_id != ctx.actor.entity_id or movement_context != 'WILLING'
            or unwilling or forced is True):
        return
    required = [feature_id] if feature_id in MOTIONS else []
    compose_motion_sequence(ctx.engine, actor, destination, ctx.intent, required=required)


def compose_motion_sequence(engine, actor, destination, intent, *, required=()):
    """One Motion normally; the owned Focus purchase permits two, with each cost.

    An action already executing a Motion must include it in the selection. This
    prevents selecting two other talents while also receiving the action's Motion.
    """
    rows = rows_of(engine, actor, selected=False)
    row = rows.get('multiple_motions') or rows.get('motion_composition')
    if row is None or not row.get('motions'):
        return
    # Public test commentary omitted.
    if any(c.condition_id == ONE_BREATH_CONDITION for c in actor.conditions.values()):
        return
    from ..movement_sequences import bind
    from .needle import spend_focus
    options = list(row['motions'])
    required = [key for key in required if key in options]
    name = 'Multiple Motions' if 'multiple_motions' in rows else 'Motion talents'
    feature_id = MULTIPLE if 'multiple_motions' in rows else row['feature_id']
    trigger = f'{MOTIONS[required[0]]}: ' if required else ''
    base_cost = ('Flash Step expends 1 Martial Focus. ' if required == [FLASH_STEP] else
                 'Unbroken Pursuit spends a Reaction and expends 1 Martial Focus. '
                 if required == [UNBROKEN] else '')
    cost = base_cost + 'One Motion: no additional cost; two Motions: expend 1 additional Martial Focus'
    count = 1
    if 'multiple_motions' in rows and focus_held(actor) and len(options) >= 2:
        composition = ask(engine, intent, checkpoint_id(engine, 'motion_count', actor.entity_id),
            actor, CHOICE_PREFIX + 'motion_count', ['one', 'two'],
            labels={'one': 'Apply one Motion: no cost',
                    'two': 'Apply two different Motions: expend one Martial Focus'},
            preferred=['two'], name=name, feature_id=feature_id,
            target_id=actor.entity_id,
            prompt=f'{trigger}{name}: {actor.display_name} begins moving to '
                   f'({destination.x + 1}, {destination.y + 1}). {base_cost}'
                   'Apply one Motion at no additional cost, or expend one additional Martial Focus to apply two different '
                   'Motions to this movement sequence. Each still needs its own trigger and costs.',
            prompt_context={'cost': cost,
                            'paying_pool': FOCUS})
        count = 2 if composition == ['two'] else 1
    remaining = [key for key in options if key not in required]
    needed = count - len(required)
    selected = list(required)
    if needed and (len(options) == 1 or required and len(remaining) == needed):
        selected += remaining
    elif needed:
        selected += ask(engine, intent, checkpoint_id(engine, 'multiple_motions', actor.entity_id),
            actor, CHOICE_PREFIX + 'multiple_motions', remaining, labels=MOTION_LABELS,
            minimum=needed, maximum=needed, default_count=needed,
            name=name, feature_id=feature_id, target_id=actor.entity_id,
            prompt=f'{trigger}{name}: {actor.display_name} is moving to '
                   f'({destination.x + 1}, {destination.y + 1}). {base_cost}'
                   f'Choose {needed} {"additional " if required else ""}Motion talent(s) for this movement sequence. '
                   f'{"Expend one additional Martial Focus." if count == 2 else "No additional Martial Focus cost."} '
                   'Each talent still needs its own trigger and costs. '
                   'This spends no Action or Reaction.',
            prompt_context={'cost': cost, 'paying_pool': FOCUS})
    if len(selected) == 2 and not spend_focus(engine, actor, MULTIPLE, 'two Motions for this movement sequence'):
        raise ValueError('Two Motions require Martial Focus')
    bind(engine, actor, 'motion', options, selected)


@hook('material_traversal')
def terrain_glide(engine, actor):
    if not owns(engine, actor, 'terrain_glide'):
        return None
    return {'mode': 'swim', 'materials': ('soil', 'snow', 'loose earth', 'sand', 'water'),
            'difficult_materials': ('soil', 'snow', 'loose earth', 'sand')}


def rows_of(engine: Any, actor: Any, *, selected: bool = True) -> dict[str, dict[str, Any]]:
    """Owned rows, normally filtered by this sequence's earning permissions.

    selected=False reads ownership for an already earned, unexpired benefit;
    it never grants movement credit from an unselected sequence.

    One read-only frame shares the rows for one unchanged creature: cover and
    movement hooks ask ownership once per ray and square. Callers only read.
    The movement-selection receipt is part of the key: bind() can change the
    selected features of the active sequence without recording a state change,
    and those selections decide whether a row is earned.
    """
    from ..movement_sequences import receipt
    from ..read_queries import shared_query

    def collect():
        from ..movement_sequences import enabled
        return {str(row.get("kind")): row for row in (getattr(engine, "typed_passive_rows", {}) or {}).get(actor.entity_id, ())
                if row.get("block") == BLOCK and row.get("kind")
                and (not selected or enabled(engine, actor, row.get('feature_id')))}

    scope = (tuple(sorted((key, tuple(values)) for key, values in receipt(engine, actor).items()))
             if selected else ())
    return shared_query(engine, ('athletics.rows_of', id(actor), selected, scope), collect, refs=(actor,))


def owns(engine: Any, actor: Any, kind: str) -> bool:
    return kind in rows_of(engine, actor)


def row_of(engine: Any, actor: Any, kind: str) -> dict[str, Any] | None:
    return rows_of(engine, actor).get(kind)


def focus_held(actor: Any) -> int:
    return int(actor.resources.get(FOCUS, 0) or 0)


def _turn_key(engine: Any, actor: Any) -> str:
    return f"athletics_turn:{engine.state.round_number}:{engine.state.current_slot_index}:{actor.entity_id}"


def used_this_turn(engine: Any, actor: Any, flag: str) -> bool:
    """Whether that once-per-turn use is already spent (a pure read, so an offer can ask without spending it)."""
    return str(actor.turn_flags.get(f"athletics_used:{flag}") or "") == _turn_key(engine, actor)


def mark_turn_use(engine: Any, actor: Any, flag: str) -> None:
    actor.turn_flags[f"athletics_used:{flag}"] = _turn_key(engine, actor)


def spent_this_turn(engine: Any, actor: Any, flag: str) -> bool:
    """Read and record one once-per-turn use. Both are strings: a saved-fight-safe turn stamp."""
    if used_this_turn(engine, actor, flag):
        return True
    mark_turn_use(engine, actor, flag)
    return False


def hostiles(engine: Any, actor: Any) -> list[Any]:
    return sorted((other for other in engine.state.actors.values()
                   if other.active and other.team_id != actor.team_id and other.entity_id != actor.entity_id),
                  key=lambda other: other.entity_id)


def _opportunity_reactors(engine: Any, mover: Any) -> list[str]:
    """Every creature that could make an Opportunity Attack against ``mover`` right now, as ids.

    The shared granted-movement path (``combat/ext/granted_movement.py``) suppresses exactly the ids it is
    handed, so a clause that is printed for every enemy has to name them all: handing it only the attacker that
    just missed left every other enemy free to attack ``mover`` for stepping out of *its* reach
    (independent review AUTO8r1, R2). The enemy test is the engine's own ``relation`` query -- the same one
    ``gate2_engine._resolve_leave_reach`` uses to collect its reactors -- so nothing the engine would not have
    attacked is exempted, and nothing it would have attacked is left standing."""
    from ..relations import ENEMY, relation

    return sorted(other.entity_id for other in engine.state.actors.values()
                  if other.active and other.entity_id != mover.entity_id
                  and relation(engine, other, mover) == ENEMY)


def _moved_ft_this_turn(engine: Any, mover: Any, previous: Any, nxt: Any) -> int:
    """How far this fighter has moved this turn, including the step being taken right now.

    ``turn_moved_ft`` counts this turn's *committed* routes; the route in progress is committed only when
    it finishes, so a single continuous 20-foot walk looks like 5, 10, 15 feet at its own checkpoints. The
    movement checkpoint's read-only context (combat/movement_steps.context) carries the feet already
    covered on the route in progress, which is what makes one uninterrupted route count as 20 feet."""
    from .. import movement_steps

    walked = turn_moved_ft(engine, mover)
    on_route = int(movement_steps.context(engine, mover).get("travelled_ft") or 0)
    return walked + max(on_route, engine.grid.distance_ft(previous, nxt) if previous is not None and nxt is not None else 0)


def _grant_step(engine: Any, actor: Any, feet: int, source: str, *, free_of_oa: bool = True) -> None:
    """Immediate movement that costs no Action: the same shape as Banner's and Formation's printed free steps."""
    actor.movement_remaining_ft += feet
    if free_of_oa:
        actor.turn_flags["oa_free_ft"] = int(actor.turn_flags.get("oa_free_ft") or 0) + feet
    engine._append_event("MOVEMENT_GRANTED", source, actor_id=actor.entity_id, payload={"distance_ft": feet})


@hook("compile_block")
def compile_athletics(block: str, spec: dict[str, Any], row: dict[str, Any], numbers: dict[str, Any]) -> list[dict[str, Any]] | None:
    """One passive row per printed clause of an Athletics feature (``rules``), or one for a single ``kind``.

    A clause may also ask for one of the shared ``motion`` row kinds (combat/motion.py: Speed, difficult terrain, Focus),
    which is how the sphere's other movement passives are declared; ``purchases`` counts a talent bought twice."""
    if block != BLOCK:
        return None
    rules = spec.get("rules") if isinstance(spec.get("rules"), list) else [spec]
    out = []
    for rule in rules:
        if not isinstance(rule, dict):
            continue
        kind = str(rule.get("kind") or "")
        if kind in KINDS:
            out.append({**row, "block": BLOCK, "kind": kind, "numbers": dict(numbers),
                        **{key: value for key, value in rule.items() if key not in {"kind", "motion"}}})
        for shared in rule.get("motion") or ():
            if str(shared) not in MOTION_KINDS:
                continue
            out.append({**row, "block": "motion", "kind": str(shared), "numbers": dict(numbers),
                        **{key: value for key, value in rule.items() if key not in {"kind", "motion"}}})
    return out or None


@hook("compile_passives")
def air_stunt_prerequisite(rows: list[dict[str, Any]], info: dict[str, Any]) -> list[dict[str, Any]]:
    """Seal the owned prerequisite; Air Stunt cannot invent Wall Stunt."""
    if "TAL_ATHLETICS_AIR_STUNT" not in info.get("owned_ids", ()):
        return rows
    return [{**row, "wall_stunt_owned": int("TAL_ATHLETICS_WALL_STUNT" in info.get("owned_ids", ()))}
            if row.get("block") == BLOCK and row.get("kind") == "air_stunt" else row for row in rows]


# Public test commentary omitted.
# Public test commentary omitted.
# Public test commentary omitted.
# Public test commentary omitted.
HEAVEN = "TAL_ATHLETICS_HEAVEN_TREADING_BODY"
SPARROWS = "TAL_ATHLETICS_SPARROW_S_PATH"
WINGS = "TAL_ATHLETICS_POWERFUL_WINGS"


def _own_fly_speed(engine: Any, actor: Any) -> int:
    """The Fly Speed this fighter already has from recorded data or this module's own rows."""
    speed = int(actor.fly_speed_ft or 0)
    if owns(engine, actor, "heaven_treading"):
        speed = max(speed, engine._effective_speed(actor))
    if owns(engine, actor, "sparrows_path"):
        speed = max(speed, int(actor.speed_ft or 0) // 2)
    for condition in actor.conditions.values():
        speed = max(speed, int((condition.data or {}).get("fly_speed_ft") or 0))
    return speed


@hook("flight")
def athletics_flight(engine: Any, actor: Any) -> dict[str, Any] | None:
    """Heaven-Treading Body (Fly Speed equal to land Speed, Hover) and Sparrow's Path (half the base land Speed)."""
    row = row_of(engine, actor, "heaven_treading")
    if row is not None:
        return {"fly_speed_ft": int(engine._effective_speed(actor)), "flight_hover": 1}
    row = row_of(engine, actor, "sparrows_path")
    if row is not None:
        return {"fly_speed_ft": max(1, int(actor.speed_ft or 0) // 2)}
    return None


@hook("climbing")
def athletics_climbing(engine: Any, actor: Any) -> dict[str, Any] | None:
    """Owned climbing clauses, returned as generic recorded-capability shapes.

    A Climb Speed removes the climbing movement surcharge; it does not waive a
    slippery/few-handholds check. Mighty Conditioning's check choice remains a
    choice on each actual check, even when the player's lower modifier wins.
    """
    rows = rows_of(engine, actor)
    capability = {}
    air = rows.get("air_stunt")
    if air and air.get("wall_stunt_owned"):
        capability["climb_virtual_wall"] = True
        capability["climb_hold_virtual"] = any(c.condition_id == AIR_SUPPORT for c in actor.conditions.values())
    if "spider_touch" in rows:
        capability["climb_speed_ft"] = max(0, int(engine._effective_speed(actor)))
        from .athletics_grip_lungs import owns as owns_grip
        if owns_grip(engine, actor, "sure_grip"):
            from .hand_occupancy import free_hands
            capability["climb_ceiling"] = True
            capability["climb_physical_disabled"] = not bool(free_hands(engine, actor))
    if "mighty_conditioning" in rows:
        capability["climb_check_abilities"] = ["STR", "DEX"]
        # Public test commentary omitted.
        # Public test commentary omitted.
        capability["climb_check_choice_name"] = "Mighty Conditioning"
        capability["climb_check_choice_source"] = MIGHTY
    return capability or None


AIR_SUPPORT = "condition:typed.air_stunt_support"


@hook("movement_begin")
def air_stunt_movement_begin(engine: Any, actor: Any, candidate: Any, intent: Any, granted_ft: Any) -> None:
    """A real chosen wall route holds only until the end of the owner's next turn."""
    row = row_of(engine, actor, "air_stunt")
    if (not row or not row.get("wall_stunt_owned") or candidate.metadata.get("movement_mode") != "climb"
            or not any(p.z for p in candidate.canonical_path)):
        return
    boundary = actor.turns_started + int(engine.state.current_actor_id != actor.entity_id)
    engine._apply_condition(actor, AIR_SUPPORT, "TAL_ATHLETICS_AIR_STUNT", actor.entity_id,
                            expires_on=f"END_OF_SOURCE_TURN_AT:{boundary}",
                            data={"label": "Air Stunt: move through air as a difficult wall; fall if unsupported at your turn's end"})


@hook("turn_end", priority=-100)
def air_stunt_turn_end(engine: Any, actor: Any) -> None:
    """Lose provisional air support; native falling retains independent protections."""
    if not owns(engine, actor, "air_stunt"):
        return
    engine._remove_condition(actor, AIR_SUPPORT, "TAL_ATHLETICS_AIR_STUNT")
    from ..falling import settle
    settle(engine, "Air Stunt: end of turn", getattr(engine, "_active_intent", None))


@hook("falling_damage")
def heaven_no_fall_damage(engine: Any, target: Any, defended: int, fall: Any, intent: Any) -> dict[str, Any] | None:
    """Heaven-Treading Body: "reduce falling damage to 0" (its "land on your feet" is Hover's ordinary landing)."""
    if not owns(engine, target, "heaven_treading"):
        return None
    return {"amount": 0, "land_prone": False}


# Public test commentary omitted.
@hook("flight")
def powerful_wings_hover(engine: Any, actor: Any) -> dict[str, Any] | None:
    """Powerful Wings: "If you possess a Fly Speed through physical wings, you may Hover."

    The fighter's own Heaven-Treading Body and Sparrow's Path rows are its physical flight; a recorded Fly Speed from any
    other source (Featherfall's protection, another sphere's temporary flight) is not wings and gets no Hover."""
    if not owns(engine, actor, "powerful_wings"):
        return None
    return {"flight_hover": 1} if _own_fly_speed(engine, actor) > 0 else None


# Public test commentary omitted.
# Public test commentary omitted.
# Public test commentary omitted.
# Public test commentary omitted.
MOVING_TARGET = "TAL_ATHLETICS_MOVING_TARGET"
MOVING_TARGET_DEEP = "condition:typed.moving_target_three_quarters"
MOVING_TARGET_LABEL = "Moving Target: Three-Quarters Cover"


def _moving_target(engine: Any, actor: Any) -> int:
    """0, 2 or 5: the cover this fighter currently has from Moving Target (pure; spends nothing)."""
    # Public test commentary omitted.
    row = rows_of(engine, actor, selected=False).get("moving_target")
    from ..movement_sequences import moved_ft
    if row is None or moved_ft(engine, actor, MOVING_TARGET) <= 20:
        return 0
    if any(c.condition_id == MOVING_TARGET_DEEP for c in actor.conditions.values()):
        return 5
    return 2


@hook("cover")
def moving_target_cover(engine: Any, attacker: Any, target: Any) -> int | None:
    """Half/Three-Quarters Cover against ranged attacks (the printed base case)."""
    if target is None:
        return None
    return _moving_target(engine, target) or None


@hook("directional_cover")
def moving_target_melee(engine: Any, attacker: Any, target: Any, ray: dict[str, Any]) -> int | None:
    """A second purchase: "Its cover applies against melee attacks as well" (melee rays only)."""
    if target is None or ray.get("purpose") != "attack" or ray.get("ranged"):
        return None
    row = rows_of(engine, target, selected=False).get("moving_target")
    if row is None or int(row.get("purchases") or 1) < 2:
        return None
    return _moving_target(engine, target) or None


@hook("compile_actions")
def moving_target_choice(info: dict[str, Any]) -> list[Any] | None:
    """A free choice: spend Martial Focus to take Three-Quarters Cover instead of Half Cover this turn.

    Not a ``setting_only`` selector: paying Martial Focus is a real cost, so the engine's ordinary payment path owns it."""
    if MOVING_TARGET not in set(info.get("owned_ids") or ()):
        return None
    from ..gate2_runtime_models import ActionDefinition, EconomyKind

    typed = {"effects": [{"type": "moving_target_deep", "applies_to": "self",
                          "evidence": "If you move at least 40 feet, expend Martial Focus to gain Three-Quarters Cover instead."}],
             "numbers": info["numbers"], "duration": {"kind": "instant"}, "riders": [], "source": MOVING_TARGET}
    return [ActionDefinition(source_definition_id=f"action:typed.{info['short']}.moving_target_deep",
                             display_name="Moving Target: Three-Quarters Cover", owner_id=info["actor_id"],
                             economy=EconomyKind.NONE, resolution_kind="TYPED", target_kind="SELF",
                             costs=((FOCUS, 1),),
                             parameters={"typed": typed, "expected_damage": 0})]


@hook("candidate_allowed")
def moving_target_choice_offered(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    typed = (getattr(action, "parameters", None) or {}).get("typed") or {}
    if typed.get("source") != MOVING_TARGET:
        return None
    if any(c.condition_id == MOVING_TARGET_DEEP for c in actor.conditions.values()):
        return False  # Public test commentary omitted.
    if focus_held(actor) < 1:
        return False
    from ..movement_sequences import moved_ft
    return None if moved_ft(engine, actor, MOVING_TARGET) >= 40 else False


@effect("moving_target_deep")
def moving_target_deep(ctx: Any, row: dict[str, Any]) -> None:
    engine, actor = ctx.engine, ctx.actor
    engine._apply_condition(actor, MOVING_TARGET_DEEP, MOVING_TARGET, actor.entity_id,
                            expires_on="START_OF_SOURCE_NEXT_TURN", data={"label": MOVING_TARGET_LABEL})


@hook("status_description")
def moving_target_text(engine: Any, holder: Any, row: Any = None, data: Any = None) -> dict[str, Any] | None:
    bonus = _moving_target(engine, holder) if holder is not None else 0
    if not bonus:
        return None
    return {"text": f"{'Three-Quarters' if bonus == 5 else 'Half'} Cover (Moving Target)"}

# Public test commentary omitted.
# Public test commentary omitted.
# Public test commentary omitted.
# Public test commentary omitted.
# Public test commentary omitted.
# Public test commentary omitted.
# Public test commentary omitted.
# Public test commentary omitted.
# Public test commentary omitted.
# Public test commentary omitted.
COURT = "TAL_ATHLETICS_COURT_OF_TEN_THOUSAND_STEPS"
COURT_STANCE = "Court of Ten Thousand Steps"
# Public test commentary omitted.
# Public test commentary omitted.
# Public test commentary omitted.
# Public test commentary omitted.
# Public test commentary omitted.
COURT_CLAUSES = "condition:typed.court_of_steps"
# Public test commentary omitted.
# Public test commentary omitted.
# Public test commentary omitted.
# Public test commentary omitted.
# Public test commentary omitted.
# Public test commentary omitted.
# Public test commentary omitted.
COURT_LEGACY_CLAUSES = "condition:typed.ignore_difficult"
COURT_CLAUSE_LABEL = "Court of Ten Thousand Steps: difficult terrain ignored, stand from Prone for free"


def _court_stance(actor: Any) -> Any | None:
    from .. import stances

    return next((condition for condition in stances.active(actor)
                 if str((condition.data or {}).get("name") or "") == COURT_STANCE), None)


def _court(engine: Any, actor: Any) -> bool:
    """Whether Court of Ten Thousand Steps is running for this fighter right now.

    Read from the persisted stance alone, never from this lane's passive row: a bundle compiled before
    those rows existed still carries the named one-minute stance, and the +20 feet Speed it has always
    been given must survive that (the retired combat/ext/bodyb_motion.py read the stance and nothing
    else). Only Court's own action puts that stance on a creature, so a fighter that does not own the
    talent can never hold one and this stays inert for everyone else."""
    return _court_stance(actor) is not None


def _court_markers(actor: Any) -> list[Any]:
    """Every instance of the printed terrain clause that Court's own stance put on this fighter.

    Both the current ``court_of_steps`` id and the ``ignore_difficult`` id an older stored cast used are
    recognised, and only when the source is Court, so one talent's instance is never confused with another's.
    There is at most one of each, but this returns a list because the early end has to take off whichever of
    them a given save happens to be holding."""
    return [condition for condition in actor.conditions.values()
            if condition.condition_id in (COURT_CLAUSES, COURT_LEGACY_CLAUSES)
            and condition.source_definition_id == COURT]


def _drop_condition(engine: Any, actor: Any, instance_id: str, source: str, *, label: str = "") -> bool:
    """Take off exactly one condition instance (``_remove_condition`` takes off every instance of the id)."""
    if instance_id not in actor.conditions:
        return False
    condition_id = actor.conditions[instance_id].condition_id
    del actor.conditions[instance_id]
    engine._append_event("CONDITION_REMOVED", source, actor_id=actor.entity_id, target_ids=(actor.entity_id,),
                         payload={"condition_id": condition_id, "instance_id": instance_id,
                                  **({"reason": label} if label else {})})
    return True


@hook("speed")
def court_speed(engine: Any, actor: Any) -> int | None:
    """+20 feet to every movement Speed while the stance runs."""
    return 20 if _court(engine, actor) else None


@hook("speed_explanation")
def court_speed_label(engine: Any, actor: Any) -> list[dict[str, Any]] | None:
    """The player-facing cause of the +20 feet (combat/ext/__init__.py movement presentation query)."""
    if not _court(engine, actor):
        return None
    return [{"label": "Court of Ten Thousand Steps", "delta_ft": 20, "source_id": COURT}]


def _apply_court_clauses(engine: Any, actor: Any) -> None:
    """Publish Court's standing clauses on its own condition id, for the stance's own clock.

    A stance that a save was already holding carries the older ``ignore_difficult`` instance instead, so it is
    migrated onto the current id here rather than left behind: both rows grant the same printed clause, and
    leaving both would show the fighter two terrain pills for one stance."""
    stance = _court_stance(actor)
    if stance is None:
        return
    markers = _court_markers(actor)
    if any(condition.condition_id == COURT_CLAUSES for condition in markers):
        return
    for condition in markers:
        _drop_condition(engine, actor, condition.instance_id, COURT, label="moved to Court's own condition")
    engine._apply_condition(actor, COURT_CLAUSES, COURT, actor.entity_id, expires_on=stance.expires_on,
                            data={"label": COURT_CLAUSE_LABEL})


@hook("technique_used")
def court_clauses(ctx: Any) -> None:
    """While the stance runs: ignore nonmagical difficult terrain (the printed clause)."""
    if str(ctx.typed.get("source") or "") == COURT:
        _apply_court_clauses(ctx.engine, ctx.actor)


@hook("turn_start")
def court_clauses_republished(engine: Any, actor: Any) -> None:
    """Re-publish the stance's clauses at a turn boundary if they are missing.

    A saved fight that already held the stance when it was stored has no clause condition of this
    lane's shape in it (it was compiled before the row existed); the printed terrain clause is part of
    the stance, not of the cast, so it comes back at the next turn rather than never."""
    _apply_court_clauses(engine, actor)


@hook("became_incapacitated")
def court_ends_incapacitated(engine: Any, actor: Any, event: Any) -> None:
    """"Court of Ten Thousand Steps ends early if you become Incapacitated" (its own instances only).

    Both of the condition ids a stored cast may carry are taken off, so a fight saved before Court had an id of
    its own loses the terrain clause with the stance instead of keeping it until that instance's own expiry."""
    stance = _court_stance(actor)
    if stance is None:
        return
    for marker in _court_markers(actor):
        _drop_condition(engine, actor, marker.instance_id, COURT)
    _drop_condition(engine, actor, stance.instance_id, stance.source_definition_id)


@hook("stand_cost")
def court_stand_free(engine: Any, actor: Any, normal_cost: int) -> int | None:
    """"stand from Prone without spending movement", read from the stance so a resumed old fight keeps it."""
    return 0 if _court(engine, actor) else None


@hook("movement_step")
def court_regain_focus(engine: Any, mover: Any, previous: Any, nxt: Any, intent: Any) -> dict[str, Any] | None:
    """"once per turn after moving at least 20 feet, regain Martial Focus"."""
    if mover is None or not _court(engine, mover) or mover.entity_id != engine.state.current_actor_id:
        return None
    if _moved_ft_this_turn(engine, mover, previous, nxt) < 20:
        return None
    # Public test commentary omitted.
    # Public test commentary omitted.
    if used_this_turn(engine, mover, "court_focus") or focus_held(mover) >= 1:
        return None
    mark_turn_use(engine, mover, "court_focus")
    engine._gain_resource(mover, FOCUS, 1, COURT)
    note(engine, COURT, mover, f"{mover.display_name} moves at least 20 feet and regains Martial Focus (Court of Ten Thousand Steps).")
    return None


@hook("after_miss")
def court_step_after_a_miss(ctx: Any, target: Any) -> None:
    """"once per turn when a hostile creature misses you, move 5 feet without provoking Opportunity Attacks".

    ``ctx.actor`` is the attacker that missed and ``target`` the creature it missed, so the stance is read
    from the creature that was attacked (the same reading combat/ext/bodyb_choices.py's Turning Guard uses).
    The move is a real, immediate and optional step resolved by the shared granted-movement path
    (combat/ext/granted_movement.py, the one implementation behind Swaying Guard's printed 5 feet), not a
    movement allowance the next turn's reset would take back."""
    from . import rider_choices

    engine, attacker = ctx.engine, ctx.actor
    if target is None or not target.active or attacker.team_id == target.team_id or not _court(engine, target):
        return
    if used_this_turn(engine, target, "court_step"):
        return
    feet = int((row_of(engine, target, "court_of_steps") or {}).get("miss_step_ft") or 5)
    if not rider_choices.step(engine, target, "court_step_after_a_miss", COURT_STANCE, attacker, feet, COURT,
                              ctx.intent, trigger=(f"{attacker.display_name} misses {target.display_name}; move up to "
                                                  f"{feet} feet without provoking any Opportunity Attack"),
                              ignored_oa=_opportunity_reactors(engine, target)):
        return
    mark_turn_use(engine, target, "court_step")
    note(engine, COURT, target,
         f"{target.display_name} moves {feet} feet without an Opportunity Attack (Court of Ten Thousand Steps).",
         (attacker,))


# Public test commentary omitted.
# Public test commentary omitted.
# Public test commentary omitted.
# Public test commentary omitted.
# Public test commentary omitted.
SPEED_BOOST = "TAL_ATHLETICS_SPEED_BOOST"
BOOST_CONDITION = "condition:typed.speed_boost"
BOOST_LABEL = "Speed Boost: +50 feet of Speed"


def _con_modifier(engine: Any, actor: Any) -> int:
    """"rounds equal to your Constitution modifier": the fighter's own persisted Constitution modifier."""
    from ..ability_checks import ability_modifier

    return int(ability_modifier(actor, "CON"))


@hook("compile_actions")
def speed_boost_actions(info: dict[str, Any]) -> list[Any] | None:
    """The printed Dash/Disengage extension rides the shared ``motion`` rows; this is the optional +50 foot boost."""
    if SPEED_BOOST not in set(info.get("owned_ids") or ()):
        return None
    from ..gate2_runtime_models import ActionDefinition, EconomyKind

    typed = {"effects": [{"type": "speed_boost", "applies_to": "self", "evidence": "expend Martial Focus to increase all movement "
                                                                                      "Speeds by 50 feet for rounds equal to your "
                                                                                      "Constitution modifier, minimum 1 round"}],
             "numbers": info["numbers"], "duration": {"kind": "rounds", "amount": 1}, "riders": [], "source": SPEED_BOOST}
    return [ActionDefinition(source_definition_id=f"action:typed.{info['short']}.speed_boost",
                             display_name="Speed Boost: +50 feet of Speed", owner_id=info["actor_id"],
                             economy=EconomyKind.NONE, resolution_kind="TYPED", target_kind="SELF", costs=((FOCUS, 1),),
                             parameters={"typed": typed, "expected_damage": 0})]


@hook("candidate_allowed")
def speed_boost_offered(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    """Once a round, and never while Exhaustion is above 2 (the printed activation limit)."""
    typed = (getattr(action, "parameters", None) or {}).get("typed") or {}
    if typed.get("source") != SPEED_BOOST:
        return None
    from . import forged_exhaustion

    if forged_exhaustion.level(actor) > 2:
        return False
    if any(c.condition_id == BOOST_CONDITION for c in actor.conditions.values()):
        return False
    return None if not used_this_turn(engine, actor, "speed_boost") else False


@effect("speed_boost")
def speed_boost(ctx: Any, row: dict[str, Any]) -> None:
    """+50 feet of Speed for rounds equal to the Constitution modifier, minimum 1 (the printed formula)."""
    engine, actor = ctx.engine, ctx.actor
    rounds = max(1, _con_modifier(engine, actor))
    engine._apply_condition(actor, BOOST_CONDITION, SPEED_BOOST, actor.entity_id,
                            expires_on=f"END_OF_SOURCE_TURN_AT:{int(actor.turns_started) + rounds}",
                            data={"label": BOOST_LABEL, "con_mod": rounds})
    note(engine, SPEED_BOOST, actor,
         f"{actor.display_name} spends Martial Focus: every movement Speed rises by 50 feet for {rounds} round"
         f"{'' if rounds == 1 else 's'}, then one level of Exhaustion.")


@hook("effect_expiring")
def speed_boost_exhaustion(engine: Any, holder: Any, row: Any) -> None:
    """"When the duration ends, gain one level of Exhaustion until completing a short or long rest"."""
    if holder is None or getattr(row, "condition_id", None) != BOOST_CONDITION:
        return
    from . import forged_exhaustion

    forged_exhaustion.add(engine, holder, 1, SPEED_BOOST)
    note(engine, SPEED_BOOST, holder, f"{holder.display_name}'s Speed Boost ends, leaving one level of Exhaustion.")


@hook("speed")
def speed_boost_speed(engine: Any, actor: Any) -> int | None:
    if not any(c.condition_id == BOOST_CONDITION for c in actor.conditions.values()):
        return None
    row = row_of(engine, actor, "speed_boost")
    return int(row.get("boost_ft") or 50) if row is not None else None


@hook("speed_explanation")
def speed_boost_label(engine: Any, actor: Any) -> list[dict[str, Any]] | None:
    if not any(c.condition_id == BOOST_CONDITION for c in actor.conditions.values()):
        return None
    return [{"label": "Speed Boost", "delta_ft": 50, "source_id": SPEED_BOOST}]


@hook("action_completed")
def speed_boost_dash_extra(engine: Any, actor: Any, economy: str, source_definition_id: str) -> None:
    """"When taking Dash or Disengage as your Action, move an additional 10 feet" (never as a Bonus Action)."""
    from .. import motion

    if economy != "ACTION" or motion.ACTIONS.get(source_definition_id) not in ("dash", "disengage"):
        return
    row = row_of(engine, actor, "speed_boost")
    if row is None:
        return
    _grant_step(engine, actor, int(row.get("action_extra_ft") or 10), SPEED_BOOST, free_of_oa=False)


# Public test commentary omitted.
# Public test commentary omitted.
# Public test commentary omitted.
# Public test commentary omitted.
# Public test commentary omitted.
# Public test commentary omitted.
# Public test commentary omitted.
FLASH_STEP = "TAL_ATHLETICS_FLASH_STEP"


@hook("compile_actions")
def flash_step_action(info: dict[str, Any]) -> list[Any] | None:
    if FLASH_STEP not in set(info.get("owned_ids") or ()):
        return None
    from ..gate2_runtime_models import ActionDefinition, EconomyKind

    typed = {"effects": [{"type": "teleport", "applies_to": "self", "distance_ft": "speed",
                          "evidence": "Teleport into your final destination without passing through intervening spaces."}],
             "numbers": info["numbers"], "duration": {"kind": "instant"}, "riders": [], "source": FLASH_STEP}
    return [ActionDefinition(source_definition_id=f"action:typed.{info['short']}.flash_step",
                             display_name="Flash Step", owner_id=info["actor_id"], economy=EconomyKind.ACTION,
                             resolution_kind="TYPED", target_kind="SELF", costs=((FOCUS, 1),),
                             parameters={"typed": typed, "expected_damage": 0})]


@hook("candidate_allowed")
def flash_step_needs_focus(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    """Only while the printed Martial Focus is held: it is the whole cost, and one Focus is the limit the text sets.

    The printed trigger is "when you take the Dash Action". The table cannot re-open a spent Action, so Flash Step is
    the Action that spends that Dash: the fighter teleports instead of walking, at their Speed, which is the distance the
    printed text measures. The Dash Action itself stays available and unchanged."""
    typed = (getattr(action, "parameters", None) or {}).get("typed") or {}
    if typed.get("source") != FLASH_STEP:
        return None
    return None if focus_held(actor) >= 1 else False


# Public test commentary omitted.
# Public test commentary omitted.
# Public test commentary omitted.
# Public test commentary omitted.
HELICOPTER = "TAL_ATHLETICS_HELICOPTER_DESCENT"
HELICOPTER_CONDITION = "condition:typed.helicopter_descent"
# Public test commentary omitted.
# Public test commentary omitted.
# Public test commentary omitted.
# Public test commentary omitted.
HELICOPTER_GEAR_WORDS = ("polearm", "rope", "chain", "whip", "tether",
                         "spear", "pike", "halberd", "trident", "spade", "guandao", "naginata")


def helicopter_gear(engine: Any, actor: Any) -> list[str]:
    """The names of the polearm, rope, chain, whip or tether items this fighter is actually holding.

    Read from the authoritative item record (weapon_family, name and tags) of every weapon
    combat/weapon_delivery.available_weapons reports as possessed, which already excludes a dropped,
    disarmed or stolen weapon. "Appropriate" is read as the printed words themselves."""
    from factory_authoring.starting_kits import item_definition

    from ..weapon_delivery import available_weapons

    names = []
    for action in available_weapons(engine, actor).values():
        item = item_definition(str(((action.parameters or {}).get("typed") or {}).get("source") or "")) or {}
        described = f"{item.get('weapon_family') or ''} {item.get('name') or ''} {item.get('tags') or ''}".lower()
        if any(word in described for word in HELICOPTER_GEAR_WORDS):
            names.append(str(item.get("name") or action.display_name))
    return names


@hook("turn_end")
def helicopter_descent(engine: Any, actor: Any) -> None:
    """Ending a turn in the air with the printed gear: a safe, upright descent for rounds equal to your Proficiency Bonus."""
    from .. import falling

    row = row_of(engine, actor, "helicopter_descent")
    if row is None or not actor.position.z or falling.supported(engine, actor):
        return
    if not helicopter_gear(engine, actor):
        return  # Public test commentary omitted.
    from ..typed_reactions import can_use_reaction, open_reaction

    if not can_use_reaction(engine, actor, None, row):
        return
    if focus_held(actor) < 1:
        return
    rounds = max(1, int(actor.proficiency_bonus))
    fall_ft = int(row.get("fall_speed_ft") or 60)
    checkpoint = checkpoint_id(engine, "helicopter_descent", actor.entity_id)
    chosen = ask(engine, getattr(engine, "_active_intent", None), checkpoint, actor, CHOICE_PREFIX + "helicopter_descent",
                 ["descend"],
                 labels={"descend": f"Fall no faster than {fall_ft} feet this round, take no falling damage if you land "
                                   f"first, and land on your feet, for {rounds} round{'' if rounds == 1 else 's'}"},
                 allow_decline=True, default="first",
                 prompt=(f"Helicopter Descent: end your turn in the air using your Reaction and one Martial Focus (your "
                         f"ki reserve) to fall no faster than {fall_ft} feet a round, take no falling damage if you land "
                         f"before {rounds} round{'' if rounds == 1 else 's'} have passed, and land on your feet instead "
                         "of falling? You can pass and simply fall."),
                 name="Helicopter Descent", feature_id=HELICOPTER)
    if not chosen:
        return
    with activation(engine, actor, HELICOPTER):
        engine._spend_resource(actor, FOCUS, 1, HELICOPTER)
        open_reaction(engine, row, actor, (), checkpoint)
        engine._apply_condition(actor, HELICOPTER_CONDITION, HELICOPTER, actor.entity_id,
                                expires_on=f"END_OF_SOURCE_TURN_AT:{int(actor.turns_started) + rounds}",
                                data={"label": f"Helicopter Descent: a safe upright fall for {rounds} round"
                                               f"{'' if rounds == 1 else 's'}",
                                      "fall_speed_ft": fall_ft, "fall_damage_immune": 1,
                                      "fall_lands_upright": 1})
        note(engine, HELICOPTER, actor,
             f"{actor.display_name} slows the fall to {fall_ft} feet a round and will land on their feet for {rounds} round"
             f"{'' if rounds == 1 else 's'}.")


# Public test commentary omitted.
# Public test commentary omitted.
# Public test commentary omitted.
# Public test commentary omitted.
DIZZYING = "TAL_ATHLETICS_DIZZYING_TUMBLE"
DIZZY_IMMUNE = "condition:typed.dizzying_tumble_immune"
DIZZY = "condition:typed.dizzy"


def _dizzy_immune_to(other: Any, mover: Any) -> bool:
    """Whether this creature is immune to *this* tumbler: "immune to your Dizzying Tumble" is per caster,
    so one fighter's successful save does not protect it from another fighter's tumble."""
    return any(condition.condition_id == DIZZY_IMMUNE and str(condition.source_actor_id or "") == mover.entity_id
               for condition in other.conditions.values())


def _leaving_neighbours(engine: Any, mover: Any, previous: Any, nxt: Any) -> list[Any]:
    """The hostile creatures this step walks away from: beside the fighter now, not beside them after it."""
    return [other for other in hostiles(engine, mover)
            if engine.grid.distance_ft(other.position, previous) <= 5
            and engine.grid.distance_ft(other.position, nxt) > 5]


@hook("movement_attempt")
def dizzying_tumble(engine: Any, mover: Any, previous: Any, nxt: Any, intent: Any) -> dict[str, Any] | None:
    """Leaving a space beside a hostile creature costs 10 feet of movement and rolls that creature's Wisdom save.

    The printed trigger names "that creature", so the fighter chooses which of the creatures it is leaving,
    and may decline: both are the player's decision, asked through the public Needle transport. Asking here is
    safe because ext.ControllerPause is a BaseException, so a hook that needs an answer unwinds the intent and
    is replayed from the same checkpoint with the answer in hand, exactly as a leave-reach Opportunity Attack
    asked mid-route is. Nothing is paid until the chosen creature is known and still able to be Dizzy."""
    row = row_of(engine, mover, "dizzying_tumble") if mover is not None else None
    if row is None or mover.entity_id != engine.state.current_actor_id:
        return None
    cost = int(row.get("cost_ft") or 10)
    if mover.movement_remaining_ft < cost or used_this_turn(engine, mover, "dizzying_tumble"):
        return None
    neighbours = [other for other in _leaving_neighbours(engine, mover, previous, nxt) if other.active]
    if not neighbours:
        return None
    labels = {other.entity_id: f"Make {other.display_name} Dizzy (Disadvantage on its attack rolls until the end of "
                              f"your next turn): costs {cost} feet of movement" for other in neighbours}
    picked = ask(engine, intent, checkpoint_id(engine, "dizzying_tumble", mover.entity_id), mover,
                 CHOICE_PREFIX + "dizzying_tumble", [other.entity_id for other in neighbours], labels=labels,
                 preferred=[other.entity_id for other in neighbours][:1], allow_decline=True, default="first",
                 prompt=(f"Dizzying Tumble: you are leaving a space beside "
                         f"{' and '.join(other.display_name for other in neighbours)}. Spend {cost} feet of your "
                         "movement to make one of them roll a Wisdom saving throw, or pass."),
                 name="Dizzying Tumble", feature_id=DIZZYING)
    if not picked:
        return None
    neighbour = engine.state.actors.get(picked[0])
    if neighbour is None or not neighbour.active or neighbour not in neighbours:
        return None  # Public test commentary omitted.
    if _dizzy_immune_to(neighbour, mover):
        note(engine, DIZZYING, mover,
             f"{mover.display_name} tumbles away from {neighbour.display_name}, which is already immune to their "
             "Dizzying Tumble; no movement is spent.", (neighbour,))
        return None
    mark_turn_use(engine, mover, "dizzying_tumble")
    mover.movement_remaining_ft -= cost
    engine._append_event("MOVEMENT_GRANTED", DIZZYING, actor_id=mover.entity_id, payload={"distance_ft": -cost})
    dc = int(row.get("numbers", {}).get("save_dc") or 0) or needle.save_dc(engine, mover)
    saved = engine._roll_save(neighbour, "WIS", dc, DIZZYING).total >= dc
    if saved:
        engine._apply_condition(neighbour, DIZZY_IMMUNE, DIZZYING, mover.entity_id, expires_on="UNTIL_REMOVED",
                                data={"against": mover.entity_id, "label": "Immune to Dizzying Tumble until a short or long rest"})
        note(engine, DIZZYING, mover,
             f"{neighbour.display_name} saves against Dizzying Tumble and is immune to it until a short or long rest.",
             (neighbour,))
        return None
    # Public test commentary omitted.
    # Public test commentary omitted.
    # Public test commentary omitted.
    # Public test commentary omitted.
    engine._apply_condition(neighbour, DIZZY, DIZZYING, mover.entity_id,
                            expires_on=f"END_OF_SOURCE_TURN_AT:{int(mover.turns_started) + 1}",
                            data={"label": f"Dizzy: Disadvantage on attack rolls (Dizzying Tumble by {mover.display_name})"})
    note(engine, DIZZYING, mover,
         f"{mover.display_name} tumbles away from {neighbour.display_name}, leaving it Dizzy: Disadvantage on its attack rolls "
         "until the end of your next turn.", (neighbour,))
    return None


# Public test commentary omitted.
# Public test commentary omitted.
# Public test commentary omitted.
# Public test commentary omitted.
# Public test commentary omitted.
# Public test commentary omitted.
# Public test commentary omitted.
# Public test commentary omitted.
# Public test commentary omitted.
# Public test commentary omitted.
# Public test commentary omitted.
# Public test commentary omitted.
# Public test commentary omitted.
# Public test commentary omitted.
# Public test commentary omitted.
# Public test commentary omitted.
# Public test commentary omitted.
# Public test commentary omitted.
# Public test commentary omitted.
# Public test commentary omitted.
# Public test commentary omitted.
# Public test commentary omitted.
# Public test commentary omitted.
# Public test commentary omitted.
# Public test commentary omitted.
# Public test commentary omitted.
# Public test commentary omitted.
MERIDIAN = "TAL_ATHLETICS_MERIDIAN_THREADING_DASH"
COORDINATED_FOCUS_SOURCE = f"passive:{COORDINATED}"
MERIDIAN_CHECK = "condition:typed.meridian_check"
MERIDIAN_LABEL = "Meridian-Threading Dash"
_RESTORED = "_athletics_focus_restored"
MERIDIAN_OPTIONS = ("step", "stand", "grapple", "check")
MERIDIAN_LABELS = {
    "step": "Move 10 feet without provoking Opportunity Attacks",
    "stand": "Stand up from lying down without spending movement",
    "grapple": "Break free of one grapple that is holding you",
    "check": "Advantage on your next Strength (Athletics) or Dexterity (Acrobatics) check",
}
GRAPPLED = "condition:typed.grappled"


@hook("state_event")
def coordinated_restored_focus(engine: Any, event: Any) -> None:
    """Stamp the sphere's own Coordinated Movement Focus grant against the resolution it happened in.

    ``event.transaction_id`` is the engine's own resolution id, so the stamp names this one execution of this
    one Action rather than an Action type that could recur on a later turn."""
    if event.event_type != "RESOURCE_GAINED" or event.source_definition_id != COORDINATED_FOCUS_SOURCE:
        return
    payload = event.payload or {}
    if payload.get("resource_id") != FOCUS or int(payload.get("gained") or 0) <= 0:
        return
    engine.__dict__[_RESTORED] = {"actor": event.actor_id,
                                  "action": getattr(engine, "_active_action_source_id", None),
                                  "transaction": str(event.transaction_id or "")}


def _focus_restored_now(engine: Any, actor: Any, economy: str, source_definition_id: str) -> bool:
    """Whether this very resolution is the one Coordinated Movement restored Martial Focus for.

    All three parts must agree: the fighter, the Action definition, and the resolution transaction. An empty
    transaction on either side never matches, so a grant recorded outside a resolution cannot be claimed. The
    stamp is consumed on the match, so one grant can only ever be claimed once even inside one resolution."""
    from .. import motion

    if economy != "ACTION" or motion.ACTIONS.get(source_definition_id) is None:
        return False
    mark = engine.__dict__.pop(_RESTORED, None)
    return bool(mark and mark.get("actor") == actor.entity_id
                and mark.get("action") == source_definition_id
                and mark.get("transaction")
                and mark.get("transaction") == str(getattr(engine, "_transaction_id", None) or ""))


@hook("action_completed")
def meridian_threading(engine: Any, actor: Any, economy: str, source_definition_id: str) -> None:
    """Coordinated Movement restored Martial Focus: offer the printed choice of one benefit."""
    row = row_of(engine, actor, "meridian_threading")
    if row is None or used_this_turn(engine, actor, "meridian_threading"):
        return
    if not _focus_restored_now(engine, actor, economy, source_definition_id):
        return
    mark_turn_use(engine, actor, "meridian_threading")
    chosen = ask(engine, getattr(engine, "_active_intent", None),
                 checkpoint_id(engine, "meridian_threading", actor.entity_id), actor,
                 CHOICE_PREFIX + "meridian_threading", list(MERIDIAN_OPTIONS),
                 labels=MERIDIAN_LABELS,
                 prompt=("Meridian-Threading Dash: Coordinated Movement has just given you back one Martial Focus "
                         "(your ki reserve). Choose one benefit."),
                 name=MERIDIAN_LABEL, feature_id=MERIDIAN)
    if chosen and chosen[0] == "step":
        feet = int(row.get("step_ft") or 10)
        _grant_step(engine, actor, feet, MERIDIAN)
        # Public test commentary omitted.
        note(engine, MERIDIAN, actor,
             f"{actor.display_name} may move {feet} more feet this turn without provoking Opportunity Attacks "
             f"({MERIDIAN_LABEL}).")
    elif chosen and chosen[0] == "stand":
        _meridian_stand(engine, actor)
    elif chosen and chosen[0] == "grapple":
        _meridian_grapple(engine, actor)
    elif chosen:
        _meridian_check(engine, actor)


def _meridian_stand(engine: Any, actor: Any) -> None:
    """"stand from Prone without spending movement": combat.posture.stand_up is the one recorded transition.

    The printed benefit is the stand itself, so nothing is left behind afterwards: a second stand still costs
    the movement it normally costs."""
    from .. import posture

    if not posture.stand_up(engine, actor, cost=0, source_id=MERIDIAN):
        return
    note(engine, MERIDIAN, actor, f"{actor.display_name} stands up without spending movement ({MERIDIAN_LABEL}).")


def _meridian_grapple(engine: Any, actor: Any) -> None:
    """"end one ordinary Grappled effect affecting you": one grip, not a pin, and not every hold at once.

    ``_remove_condition`` takes off every instance of a condition id, which would end another grappler's hold
    as well, so exactly the chosen instance is taken off here (the same per-instance transition
    combat/posture.py stand_up uses). With more than one ordinary hold on it, which one is the fighter's to
    name, so it is asked.

    Not reported through combat/ext/hold_escapes.py: that shared seam records escapes, and this creature was
    never escaping -- it simply let the hold go, which its docstring lists as deliberately not reported."""
    holds = [(instance_id, condition) for instance_id, condition in actor.conditions.items()
             if condition.condition_id == GRAPPLED]
    if not holds:
        note(engine, MERIDIAN, actor, f"{actor.display_name} is not grappled, so {MERIDIAN_LABEL} spends nothing.")
        return
    if len(holds) > 1:
        labels = {}
        for instance_id, condition in holds:
            holder = engine.state.actors.get(str(condition.source_actor_id or ""))
            labels[instance_id] = (f"The hold {holder.display_name} has on you" if holder is not None
                                   else "An unnamed hold on you")
        picked = ask(engine, getattr(engine, "_active_intent", None),
                     checkpoint_id(engine, "meridian_grapple", actor.entity_id), actor,
                     CHOICE_PREFIX + "meridian_grapple", [instance_id for instance_id, _ in holds], labels=labels,
                     prompt="Meridian-Threading Dash: which one of the grapples holding you do you end?",
                     name=MERIDIAN_LABEL, feature_id=MERIDIAN)
        chosen = next(((instance_id, condition) for instance_id, condition in holds if instance_id in picked), None)
    else:
        chosen = holds[0]
    if chosen is None:
        return
    instance_id, released = chosen
    # Public test commentary omitted.
    # Public test commentary omitted.
    # Public test commentary omitted.
    # Public test commentary omitted.
    # Public test commentary omitted.
    holder = engine.state.actors.get(str(released.source_actor_id or ""))
    _drop_condition(engine, actor, instance_id, MERIDIAN, label="MERIDIAN")
    note(engine, MERIDIAN, actor,
         f"{actor.display_name} breaks free of the grapple ({MERIDIAN_LABEL}).",
         tuple(creature for creature in (holder,) if creature is not None and creature.active))


def _meridian_check(engine: Any, actor: Any) -> None:
    """"gain Advantage on your next Strength (Athletics) or Dexterity (Acrobatics) check before the end of your next turn"."""
    engine._apply_condition(actor, MERIDIAN_CHECK, MERIDIAN, actor.entity_id, expires_on="END_OF_HOLDER_NEXT_TURN",
                            data={"label": "Advantage on your next Strength (Athletics) or Dexterity (Acrobatics) check"})
    note(engine, MERIDIAN, actor,
         f"{actor.display_name}'s next Strength (Athletics) or Dexterity (Acrobatics) check has Advantage "
         f"until the end of their next turn ({MERIDIAN_LABEL}).")


@hook("ability_check_mode")
def meridian_check_mode(engine: Any, actor: Any, ability: str, skill: Any, against: Any) -> str | None:
    """The printed Strength (Athletics) / Dexterity (Acrobatics) pair, spent by the check that takes it."""
    if str(ability).upper() not in ("STR", "DEX") or str(skill or "") not in ("Athletics", "Acrobatics"):
        return None
    held = [condition for condition in actor.conditions.values() if condition.condition_id == MERIDIAN_CHECK]
    if not held:
        return None
    engine._remove_condition(actor, MERIDIAN_CHECK, MERIDIAN)
    return "ADVANTAGE"


@hook("stand_cost")
def meridian_free_stand(engine: Any, actor: Any, normal_cost: int) -> int | None:
    """No standing entitlement of its own: the printed benefit is the one stand ``_meridian_stand`` makes, so a
    second stand costs the movement it normally costs."""
    return None


# Public test commentary omitted.
# Public test commentary omitted.
# Public test commentary omitted.
# Public test commentary omitted.
# Public test commentary omitted.
# Public test commentary omitted.
# Public test commentary omitted.
# Public test commentary omitted.
# Public test commentary omitted.
# Public test commentary omitted.
# Public test commentary omitted.
PURSUIT = "TAL_ATHLETICS_FLOWING_PURSUIT"
PURSUIT_OA = "condition:typed.flowing_pursuit_no_oa"
PURSUIT_JUMP = "condition:typed.flowing_pursuit_jump"
# Public test commentary omitted.
# Public test commentary omitted.
# Public test commentary omitted.
AC_AGAINST = "condition:typed.ac_against"
PURSUIT_LABELS = {
    "no_oa": "Ignore that creature's Opportunity Attacks for the rest of this turn",
    "ac": "Gain 2 Armor Class against that creature until the start of your next turn",
    "jump": "Add 5 feet to one jump for the rest of this turn",
}


def _turn_legs(engine: Any, actor: Any) -> list[tuple[Any, Any]]:
    """This turn's own willing movement legs as (start, end) squares, oldest first.

    The same recorded-event walk as combat.ext.hold_still.moved_ft, its one implementation: teleports count as the
    ground they cross and forced displacement does not count at all."""
    from ..gate2_runtime_models import Position

    legs: list[tuple[Any, Any]] = []
    for event in reversed(engine.events):
        if event.event_type == "TURN_STARTED" and event.actor_id == actor.entity_id:
            break
        if event.event_type != "MOVEMENT_COMMITTED" or event.actor_id != actor.entity_id:
            continue
        payload = event.payload or {}
        if payload.get("forced"):
            continue
        selected = payload.get('movement_selections', {}).get('motion')
        if selected is not None and PURSUIT not in selected:
            continue
        path = [Position(**cell) for cell in payload.get("path") or () if isinstance(cell, dict)]
        if len(path) >= 2:
            legs.append((path[0], path[-1]))
    legs.reverse()
    return legs


def _pursuit_target(engine: Any, actor: Any, row: dict[str, Any]) -> Any | None:
    """The first hostile creature this turn's movement closed at least the printed distance toward."""
    legs = _turn_legs(engine, actor)
    if not legs:
        return None
    close_ft = int(row.get("close_ft") or 20)
    return next((other for other in hostiles(engine, actor)
                 if sum(engine.grid.distance_ft(start, other.position)
                        - engine.grid.distance_ft(end, other.position)
                        for start, end in legs) >= close_ft), None)


def _offer_pursuit(engine: Any, actor: Any) -> None:
    """"When you move at least 20 feet toward one creature during your turn, choose one" -- once per creature per turn.

    Asked at the two points after a move that may safely put a question to a player (a completed Action and the end
    of the turn, both of which other printed choices already use), so the closing movement itself is never paused."""
    row = row_of(engine, actor, "flowing_pursuit")
    if row is None or actor.entity_id != engine.state.current_actor_id:
        return
    target = _pursuit_target(engine, actor, row)
    if target is None or spent_this_turn(engine, actor, f"flowing_pursuit:{target.entity_id}"):
        return
    mark_turn_use(engine, actor, f"flowing_pursuit:{target.entity_id}")
    chosen = ask(engine, getattr(engine, "_active_intent", None),
                 checkpoint_id(engine, "flowing_pursuit", actor.entity_id, target.entity_id), actor,
                 CHOICE_PREFIX + "flowing_pursuit", ["no_oa", "ac", "jump"],
                 labels=PURSUIT_LABELS,
                 prompt=(f"Flowing Pursuit: you closed at least 20 feet of ground toward {target.display_name} this "
                         "turn. Choose one benefit against that creature."),
                 target_id=target.entity_id, name="Flowing Pursuit", feature_id=PURSUIT)
    if not chosen or chosen[0] not in PURSUIT_LABELS:
        return
    label = PURSUIT_LABELS[chosen[0]]
    if chosen[0] == "no_oa":
        engine._apply_condition(actor, PURSUIT_OA, PURSUIT, actor.entity_id, expires_on="END_OF_CURRENT_TURN",
                                data={"against": target.entity_id,
                                      "label": f"{target.display_name} cannot make an Opportunity Attack against you this turn"})
    elif chosen[0] == "ac":
        engine._apply_condition(actor, AC_AGAINST, PURSUIT, actor.entity_id, expires_on="START_OF_SELF_NEXT_TURN",
                                data={"against": target.entity_id, "amount": int(row.get("ac_bonus") or 2),
                                      "label": f"+{int(row.get('ac_bonus') or 2)} Armor Class against {target.display_name}"})
    else:
        engine._apply_condition(actor, PURSUIT_JUMP, PURSUIT, actor.entity_id, expires_on="END_OF_CURRENT_TURN",
                                data={"jump_bonus_ft": 5,
                                      "label": "Your next jump this turn reaches 5 feet higher"})
    note(engine, PURSUIT, actor, f"{actor.display_name}: {label} (Flowing Pursuit).", (target,))


@hook("action_completed")
def flowing_pursuit_after_action(engine: Any, actor: Any, economy: str, source_definition_id: str) -> None:
    _offer_pursuit(engine, actor)


@hook("turn_end")
def flowing_pursuit_at_turn_end(engine: Any, actor: Any) -> None:
    _offer_pursuit(engine, actor)


@hook("opportunity_allowed")
def flowing_pursuit_no_oa(engine: Any, reactor: Any, mover: Any) -> bool | None:
    """"ignore Opportunity Attacks from that creature" for the rest of the turn that earned it."""
    if mover is None or reactor is None:
        return None
    held = [condition for condition in mover.conditions.values() if condition.condition_id == PURSUIT_OA]
    if any(str((condition.data or {}).get("against") or "") == reactor.entity_id for condition in held):
        return False
    return None


@hook("event")
def pursuit_jump_spent(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    """"add 5 feet to *one* jump": the bonus ends with the jump it was bought for.

    Spent when a jump is actually committed (``MOVEMENT_COMMITTED`` in jump mode), never while a menu is being
    quoted: combat/flight.py asks jump_bonus_ft for every legal jump destination, so a reader that consumed the
    bonus would spend it on the first square the player merely looked at."""
    if event_type != "MOVEMENT_COMMITTED":
        return
    event = engine.events[-1]
    payload = event.payload or {}
    if payload.get("movement_mode") != "jump" or payload.get("forced"):
        return
    mover = engine.state.actors.get(str(kwargs.get("actor_id") or ""))
    if mover is None:
        return
    held = [condition for condition in mover.conditions.values() if condition.condition_id == PURSUIT_JUMP]
    for condition in held:
        _drop_condition(engine, mover, condition.instance_id, PURSUIT, label="JUMP_TAKEN")
    if held:
        note(engine, PURSUIT, mover, f"{mover.display_name}'s Flowing Pursuit jump bonus is used by that jump.")


@hook("jump_bonus_ft")
def athletics_jump_bonus_ft(engine: Any, actor: Any) -> int | None:
    """The module's one jump_bonus_ft reader, shared by both printed sources of flat jump height:
    Polearm Vaulter's Bonus Action increase and Flowing Pursuit's "+5 feet to one jump". A pure read;
    ``pursuit_jump_spent`` is what ends the single-use one when a jump is actually committed."""
    return sum(int((condition.data or {}).get("jump_bonus_ft") or 0)
               for condition in actor.conditions.values()
               if condition.condition_id != VAULTER_JUMP or vault_gear(engine, actor)
               if condition.condition_id in (VAULTER_JUMP, PURSUIT_JUMP)) or None


# Public test commentary omitted.
# Public test commentary omitted.
# Public test commentary omitted.
# Public test commentary omitted.
ONE_BREATH = "TAL_ATHLETICS_ONE_BREATH_TEN_THOUSAND_STEPS"
ONE_BREATH_CONDITION = "condition:typed.one_breath_steps"
_ONE_BREATH_FT = "athletics_one_breath_ft"


@hook("technique_used")
def one_breath_steps(ctx: Any) -> None:
    """Start counting this activation's movement: the printed Focus returns every 20 feet from here on."""
    engine, actor = ctx.engine, ctx.actor
    if str(ctx.typed.get("source") or "") != ONE_BREATH:
        return
    actor.turn_flags[_ONE_BREATH_FT] = "0"
    engine._apply_condition(actor, ONE_BREATH_CONDITION, ONE_BREATH, actor.entity_id, expires_on="END_OF_CURRENT_TURN",
                            data={"label": "One Breath, Ten Thousand Steps: Martial Focus returns every 20 feet you move"})


@hook("movement_step")
def one_breath_focus(engine: Any, mover: Any, previous: Any, nxt: Any, intent: Any) -> dict[str, Any] | None:
    """One Martial Focus for each further 20 feet of movement while the activation runs."""
    row = row_of(engine, mover, "one_breath") if mover is not None else None
    if row is None or mover.entity_id != engine.state.current_actor_id:
        return None
    if not any(c.condition_id == ONE_BREATH_CONDITION for c in mover.conditions.values()):
        return None
    every = max(1, int(row.get("focus_ft") or 20))
    walked = int(mover.turn_flags.get(_ONE_BREATH_FT) or 0) + engine.grid.distance_ft(previous, nxt)
    mover.turn_flags[_ONE_BREATH_FT] = str(walked)
    while walked >= every:
        walked -= every
        if focus_held(mover) >= 1:
            continue
        engine._gain_resource(mover, FOCUS, 1, ONE_BREATH)
        note(engine, ONE_BREATH, mover,
             f"{mover.display_name} moves {every} feet and regains Martial Focus (One Breath, Ten Thousand Steps).")
    mover.turn_flags[_ONE_BREATH_FT] = str(walked)
    return None


# Public test commentary omitted.
# Public test commentary omitted.
# Public test commentary omitted.
# Public test commentary omitted.
VAULTER = "TAL_ATHLETICS_POLEARM_VAULTER"
VAULTER_JUMP = "condition:typed.polearm_vaulter_jump"


# Public test commentary omitted.
UNBROKEN = "TAL_ATHLETICS_UNBROKEN_PURSUIT"


@hook("reaction_subject_allowed")
def unbroken_subject(engine: Any, actor: Any, subject: Any, row: dict[str, Any]) -> bool | None:
    """Pursuit observes a real visible creature, including allies, within live Speed."""
    if row.get("feature_id") != UNBROKEN:
        return None
    from ..targeting import line_of_effect
    return bool(subject is not None and engine._line_of_sight_actor_to_actor(actor, subject)
                and line_of_effect(engine, actor, target=subject))


def notify_pursuit(engine: Any, actor: Any, feet: int) -> None:
    """Publish nonwalking willing movement only to the owned Pursuit row.

    Walking already publishes its native event. Other reaction consumers retain
    their own movement contracts; this listener does not widen their triggers.
    """
    if feet <= 0 or not any(row.get("feature_id") == UNBROKEN
                           for rows in (getattr(engine, "typed_reaction_rows", {}) or {}).values() for row in rows):
        return
    from ..typed_reactions import dispatch_creature_reactions
    dispatch_creature_reactions(engine, actor, "moved", moved_ft=feet,
                               accept=lambda row, watcher: row.get("feature_id") == UNBROKEN)


@hook("teleport_settled")
def pursuit_after_teleport(ctx: Any, actor: Any, start: Any, end: Any, unwilling: bool) -> None:
    if unwilling:
        return
    # Public test commentary omitted.
    # Public test commentary omitted.
    receipt = next((event for event in reversed(ctx.engine.events)
                    if event.event_type == 'MOVEMENT_COMMITTED' and event.actor_id == actor.entity_id
                    and event.payload.get('teleport')
                    and event.payload.get('destination') == end.model_dump(mode='json')
                    and (not getattr(ctx, 'source', None) or event.source_definition_id == ctx.source)), None)
    if receipt is not None and receipt.payload.get('forced') is False:
        notify_pursuit(ctx.engine, actor, ctx.engine.grid.distance_ft(start, end))


@hook("event", nested=True)
def pursuit_after_reaction_move(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    payload = kwargs.get("payload") or {}
    if (event_type != "MOVEMENT_COMMITTED" or not payload.get("reaction") or payload.get("forced") is not False
            or "granted_cost_ft" in payload):
        return
    from ..gate2_runtime_models import Position
    path = [Position(**p) for p in payload.get("path") or ()]
    actor = engine.state.actors.get(kwargs.get("actor_id"))
    if actor is not None and path:
        notify_pursuit(engine, actor, sum(engine.grid.distance_ft(a, b) for a, b in zip(path, path[1:])))


@effect("athletics_unbroken_pursuit", harmful=False)
def unbroken_pursuit_move(ctx: Any, row: dict[str, Any]) -> None:
    """Choose any closer native route within half Speed; exempt only the mover."""
    from . import granted_movement
    from ..gate2_runtime_models import ActionIntent
    engine, actor, target = ctx.engine, ctx.actor, ctx.target
    if target is None or ctx.typed.get("source") != UNBROKEN:
        return
    feet = max(0, engine._effective_speed(actor) // 2)
    start_gap = engine._distance_actor_to_actor(actor, target)
    candidates = [c for c in granted_movement.choices(engine, actor, feet)
                  if c.destination is not None
                  and engine._distance_actor_to_actor(actor, target, actor_position=c.destination) < start_gap]
    if not candidates:
        return
    candidates.sort(key=lambda c: (engine._distance_actor_to_actor(actor, target, actor_position=c.destination),
                                   c.movement_cost_ft, c.candidate_id))
    choices = {c.candidate_id: c for c in candidates}
    picked = ask(engine, ctx.intent, checkpoint_id(engine, "unbroken_pursuit", actor.entity_id, target.entity_id),
                 actor, CHOICE_PREFIX + "unbroken_pursuit", list(choices),
                 labels={key: f"{c.display_name} ({c.movement_cost_ft} feet)" for key, c in choices.items()},
                 preferred=[candidates[0].candidate_id], allow_decline=True, target_id=target.entity_id,
                 name="Unbroken Pursuit", feature_id=UNBROKEN,
                 prompt=f"Unbroken Pursuit: {target.display_name} moved willingly. Choose where {actor.display_name} "
                        f"moves, up to {feet} feet, ending closer. Only {target.display_name}'s Opportunity Attacks are avoided.")
    if not picked or picked[0] not in choices:
        return
    candidate = choices[picked[0]]
    parent = ctx.intent or getattr(engine, "_active_intent", None)
    if parent is None:
        raise ValueError("Unbroken Pursuit requires a recorded triggering action")
    intent = ActionIntent(intent_id=parent.intent_id + ":pursuit", decision_id=candidate.decision_id,
                          candidate_id=candidate.candidate_id, state_version=candidate.state_version,
                          actor_id=actor.entity_id, destination=candidate.destination,
                          movement_path=candidate.canonical_path,
                          movement_mode=candidate.metadata.get("movement_mode", "walk"),
                          reaction_decisions=parent.reaction_decisions)
    granted_movement.move(engine, actor, candidate, intent, feet, [target.entity_id], name="Unbroken Pursuit",
                          movement_context={'feature_id': UNBROKEN})


@hook("compile_actions")
def polearm_vaulter_action(info: dict[str, Any]) -> list[Any] | None:
    """The Bonus Action that buys the printed jump increase; the ordinary movement budget is not charged for it."""
    if VAULTER not in set(info.get("owned_ids") or ()):
        return None
    from ..gate2_runtime_models import ActionDefinition, EconomyKind

    typed = {"effects": [{"type": "polearm_vaulter_jump", "applies_to": "self", "axis": "vertical",
                          "evidence": "expend Martial Focus as a Bonus Action to increase: horizontal jump distance by "
                                      "10 feet; or jump height by 5 feet"}],
             "numbers": info["numbers"], "duration": {"kind": "instant"}, "riders": [], "source": VAULTER}
    height = ActionDefinition(source_definition_id=f"action:typed.{info['short']}.polearm_vaulter_jump",
                             display_name="Polearm Vaulter: jump 5 feet higher", owner_id=info["actor_id"],
                             economy=EconomyKind.BONUS_ACTION, resolution_kind="TYPED", target_kind="SELF", costs=((FOCUS, 1),),
                             parameters={"typed": typed, "expected_damage": 0})
    horizontal = height.model_copy(update={
        "source_definition_id": f"action:typed.{info['short']}.polearm_vaulter_distance",
        "display_name": "Polearm Vaulter: jump 10 feet farther",
        "parameters": {"typed": {**typed, "effects": [{**typed['effects'][0], 'axis': 'horizontal'}]}, "expected_damage": 0}})
    return [height, horizontal]


def vault_gear(engine: Any, actor: Any) -> list[str]:
    """Actual held poles/polearms from owner item records, never a scene guess."""
    from ..weapon_delivery import ready_weapons
    from factory_authoring.starting_kits import item_definition
    words = ("polearm", "pole", "staff", "spear", "pike", "halberd", "trident", "spade", "guandao", "naginata")
    names = []
    for action in ready_weapons(engine, actor).values():
        item = item_definition(str((action.parameters.get('typed') or {}).get('source') or '')) or {}
        described = f"{item.get('weapon_family') or ''} {item.get('name') or ''} {item.get('tags') or ''}".lower()
        if any(word in described for word in words):
            names.append(str(item.get('name') or action.display_name))
    from .. import carry
    for carried in (carry.carrying_of(engine, actor.entity_id) or {}).get('items') or ():
        item = item_definition(str(carried.get('item_id') or '')) or {}
        described = f"{item.get('weapon_family') or ''} {item.get('name') or ''} {item.get('tags') or ''}".lower()
        if any(word in described for word in words) and carry.holds(engine, actor, carried['key']):
            names.append(str(item.get('name') or carried.get('name') or 'Pole'))
    return sorted(set(names))


@hook("movement_credit_allowed")
def vault_credit_allowed(engine: Any, actor: Any, condition: Any) -> bool | None:
    if condition.condition_id != VAULTER_JUMP:
        return None
    return bool(vault_gear(engine, actor))


@hook("jump_flat_bonus_ft")
def vault_flat_height(engine: Any, actor: Any) -> int | None:
    if not any(c.condition_id == VAULTER_JUMP for c in actor.conditions.values()) or not vault_gear(engine, actor):
        return None
    return max((int(c.data.get('jump_bonus_ft') or 0) for c in actor.conditions.values()
                if c.condition_id == VAULTER_JUMP), default=0)


@hook("jump_distance_bonus_ft")
def vault_horizontal_distance(engine: Any, actor: Any) -> int | None:
    if not any(c.condition_id == VAULTER_JUMP for c in actor.conditions.values()) or not vault_gear(engine, actor):
        return None
    return max((int(c.data.get('jump_distance_bonus_ft') or 0) for c in actor.conditions.values()
                if c.condition_id == VAULTER_JUMP), default=0)


@hook("event", nested=True)
def vault_jump_spent(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    payload = kwargs.get('payload') or {}
    if (event_type != 'MOVEMENT_COMMITTED' or payload.get('movement_mode') != 'jump'
            or payload.get('forced') is not False or len(payload.get('path') or ()) < 2):
        return
    actor = engine.state.actors.get(kwargs.get('actor_id'))
    if actor is None:
        return
    purchased = next((c for c in actor.conditions.values() if c.condition_id == VAULTER_JUMP), None)
    if purchased is None:
        return
    path = payload['path']
    # Public test commentary omitted.
    # Public test commentary omitted.
    if purchased.data.get('movement_credit_axis') == 'vertical' and not any(
            b.get('z', 0) > a.get('z', 0) for a, b in zip(path, path[1:])):
        return
    engine._remove_condition(actor, VAULTER_JUMP, VAULTER)


@hook("candidate_allowed")
def polearm_vaulter_offered(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    """Martial Focus is the whole cost, and the increase lasts for the jump it was bought for."""
    typed = (getattr(action, "parameters", None) or {}).get("typed") or {}
    if typed.get("source") != VAULTER:
        return None
    from ..falling import supported
    if not vault_gear(engine, actor) or not supported(engine, actor):
        return False
    if any(c.condition_id == VAULTER_JUMP for c in actor.conditions.values()):
        return False
    return None if focus_held(actor) >= 1 else False


@effect("polearm_vaulter_jump")
def polearm_vaulter_jump(ctx: Any, row: dict[str, Any]) -> None:
    """+5 feet of jump height until the end of this turn; it needs no Strength and no movement left to spend."""
    engine, actor = ctx.engine, ctx.actor
    horizontal = row.get('axis') == 'horizontal'
    feet = 10 if horizontal else 5
    axis = 'horizontal' if horizontal else 'vertical'
    description = f"Your next pole vault this turn reaches {feet} feet {'farther' if horizontal else 'higher'}; the increase costs no movement"
    engine._apply_condition(actor, VAULTER_JUMP, VAULTER, actor.entity_id, expires_on="END_OF_CURRENT_TURN",
                            data={"jump_bonus_ft": 0 if horizontal else feet, 'jump_distance_bonus_ft': feet if horizontal else 0,
                                  'movement_credit_mode': 'jump', 'movement_credit_axis': axis,
                                  'movement_credit_ft': feet, 'jump_allow_unsupported': 1, 'label': description})
    note(engine, VAULTER, actor, f"{actor.display_name}: {description} (Polearm Vaulter; Bonus Action and Martial Focus).")


# Public test commentary omitted.
# Public test commentary omitted.
# Public test commentary omitted.
# Public test commentary omitted.
# Public test commentary omitted.
# Public test commentary omitted.
MIGHTY = "TAL_ATHLETICS_MIGHTY_CONDITIONING"


@hook("jump_ability")
def mighty_conditioning_jump(engine: Any, actor: Any) -> str | None:
    """"use Dexterity instead of Strength when determining jump distance or height", when Dexterity is the better score."""
    if not owns(engine, actor, "mighty_conditioning"):
        return None
    from ..ability_checks import ability_modifier

    return "DEX" if ability_modifier(actor, "DEX") > ability_modifier(actor, "STR") else None


# Public test commentary omitted.
CAPOEIRA = "TAL_ATHLETICS_CAPOEIRA_SPIN"
CAPOEIRA_READY = "athletics_capoeira_started_prone"
CAPOEIRA_BOUNDARY = "athletics_capoeira_round_keep_prone"


@hook("turn_boundary_start")
def capoeira_keep_starting_posture(engine: Any, actor: Any) -> None:
    """Keep the optional bonus strike available instead of automatically paying to stand.

    The engine's start boundary otherwise stands Prone creatures automatically.
    This marker survives the boundary's round-flag reset, then is removed on
    TURN_STARTED. It vetoes only that automatic transition, never a later stand.
    """
    if not owns(engine, actor, "capoeira_spin"):
        return
    from ..posture import prone_conditions

    if prone_conditions(actor):
        actor.turn_flags[CAPOEIRA_BOUNDARY] = 1


@hook("stand_allowed")
def capoeira_preserve_bonus_choice(engine: Any, actor: Any) -> bool | None:
    if not owns(engine, actor, "capoeira_spin"):
        return None
    return False if actor.turn_flags.get(CAPOEIRA_BOUNDARY) else None


@hook("state_event")
def capoeira_boundary_finished(engine: Any, event: Any) -> None:
    if event.event_type == "TURN_STARTED":
        actor = engine.state.actors.get(event.actor_id)
        if actor is not None and owns(engine, actor, "capoeira_spin"):
            actor.turn_flags.pop(CAPOEIRA_BOUNDARY, None)


@hook("turn_start_choice")
def capoeira_starting_posture(engine: Any, actor: Any) -> None:
    """Snapshot the printed start-of-turn requirement after start-of-turn expiry."""
    if not owns(engine, actor, "capoeira_spin"):
        return
    from ..posture import prone_conditions

    if prone_conditions(actor):
        actor.turn_flags[CAPOEIRA_READY] = 1


@hook("compile_basic_actions")
def capoeira_bonus_strike(info: dict[str, Any]) -> list[Any] | None:
    if CAPOEIRA not in set(info.get("owned_ids") or ()):
        return None
    from .basic_unarmed import strike_payload
    from ..gate2_runtime_models import ActionDefinition, EconomyKind

    profile = info["attack_profiles"]["unarmed"]
    typed = strike_payload(info["numbers"], info["pb"], info["mods"], 1, profile["on_hit"])
    typed.update(source=CAPOEIRA)
    # Public test commentary omitted.
    typed["effects"][0]["strike_with"] = "unarmed"
    typed["effects"].insert(0, {"type": "capoeira_stand", "applies_to": "self"})
    return [ActionDefinition(
        source_definition_id=f"action:typed.{info['short']}.capoeira_spin",
        display_name="Capoeira Spin: stand and make one Unarmed Strike", owner_id=info["actor_id"],
        economy=EconomyKind.BONUS_ACTION, resolution_kind="TYPED", target_kind="HOSTILE_ENTITY", range_ft=5,
        parameters={"typed": typed, "expected_damage": max(0, 1 + info["mods"].get("STR", 0))
                    + profile["expected_extra_damage"]},
    )]


@hook("candidate_allowed")
def capoeira_stand_offered(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    typed = (getattr(action, "parameters", None) or {}).get("typed") or {}
    if not any(e.get("type") == "capoeira_stand" for e in typed.get("effects") or ()):
        return None
    from ..posture import standing_cost

    return bool(owns(engine, actor, "capoeira_spin") and actor.turn_flags.get(CAPOEIRA_READY)
                and standing_cost(engine, actor, cost=0) is not None)


@effect("capoeira_stand")
def capoeira_stand(ctx: Any, eff: dict[str, Any]) -> None:
    from ..posture import stand_up

    if not ctx.actor.turn_flags.get(CAPOEIRA_READY) or not stand_up(
            ctx.engine, ctx.actor, source_id=CAPOEIRA, cost=0):
        raise ValueError("Capoeira Spin requires starting your turn Prone and being able to stand.")


@hook("attack_mode_removed")
def capoeira_unarmed_posture(engine: Any, attacker: Any, target: Any, ranged: Any) -> list[str] | None:
    if not owns(engine, attacker, "capoeira_spin"):
        return None
    from .attack_scope import current

    frame = current(engine)
    if (frame and frame["actor_id"] == attacker.entity_id and frame["target_id"] == target.entity_id
            and frame["effect"].get("attack_kind") == "unarmed"):
        return ["DISADVANTAGE:prone"]
    return None


@hook("button_description", priority=-10)
def capoeira_help(row: dict[str, Any]) -> str | None:
    typed = (row.get("parameters") or {}).get("typed") or {}
    if any(e.get("type") == "capoeira_stand" for e in typed.get("effects") or ()):
        return ("Bonus Action, only if you started this turn Prone: stand without spending movement, "
                "then make one Unarmed Strike against a creature within 5 feet. No Martial Focus cost.")


# Public test commentary omitted.
# Public test commentary omitted.
# Public test commentary omitted.
TUMBLE_SOURCE = "system:combat.tumble"
TUMBLE_PERMISSION = "condition:typed.athletics_tumble"
SUDDEN_FLANK = "TAL_ATHLETICS_SUDDEN_FLANK"
WHIRLWIND_FLIP = "TAL_ATHLETICS_WHIRLWIND_FLIP"


@hook("compile_actions")
def tumble_actions(info: dict[str, Any]) -> list[Any] | None:
    if not {SUDDEN_FLANK, WHIRLWIND_FLIP} & set(info.get("owned_ids") or ()):
        return None
    from ..gate2_runtime_models import ActionDefinition, EconomyKind

    return [ActionDefinition(
        source_definition_id=f"action:typed.{info['short']}.tumble.{key}",
        display_name=f"Tumble ({label}): Acrobatics contest", owner_id=info["actor_id"], economy=economy,
        resolution_kind="TYPED", target_kind="HOSTILE_ENTITY", range_ft=5,
        parameters={"typed": {"effects": [{"type": "athletics_tumble"}], "numbers": info["numbers"],
                              "duration": {"kind": "instant"}, "riders": [], "source": TUMBLE_SOURCE},
                    "expected_damage": 0},
    ) for key, label, economy in (("action", "Action", EconomyKind.ACTION),
                                  ("bonus", "Bonus Action", EconomyKind.BONUS_ACTION))]


def tumble_permission(actor: Any, target_id: str) -> Any | None:
    """Public pure lookup; a permission is scoped to one named creature, not all enemies."""
    return next((c for c in actor.conditions.values() if c.condition_id == TUMBLE_PERMISSION
                 and c.data.get("target_id") == target_id and not c.data.get("left")), None)


@effect("athletics_tumble")
def tumble_contest(ctx: Any, eff: dict[str, Any]) -> None:
    from ..typed_executor import resolve_opposed_check

    if ctx.target is None:
        return
    check = {"ability": "DEX", "skill": "Acrobatics"}
    result = resolve_opposed_check(ctx, ctx.target, check, check)
    if not result.success:
        note(ctx.engine, TUMBLE_SOURCE, ctx.actor,
             f"Tumble: {ctx.target.display_name} blocks your attempt; you gain no passage.", (ctx.target,))
        return
    # Public test commentary omitted.
    for c in list(ctx.actor.conditions.values()):
        if c.condition_id == TUMBLE_PERMISSION and c.data.get("target_id") == ctx.target.entity_id:
            _drop_condition(ctx.engine, ctx.actor, c.instance_id, TUMBLE_SOURCE)
    ctx.engine._apply_condition(ctx.actor, TUMBLE_PERMISSION, TUMBLE_SOURCE, ctx.actor.entity_id,
        expires_on="END_OF_CURRENT_TURN", data={"target_id": ctx.target.entity_id, "entered": 0, "left": 0,
            "label": f"Tumble through {ctx.target.display_name}'s space once this turn"})
    note(ctx.engine, TUMBLE_SOURCE, ctx.actor,
         f"Tumble: you may move through {ctx.target.display_name}'s space once this turn, spending your movement; "
         "you cannot stop in its space.", (ctx.target,))
    if owns(ctx.engine, ctx.actor, "whirlwind_flip"):
        needle.regain_focus(ctx.engine, ctx.actor, WHIRLWIND_FLIP, "successful Tumble check")


@hook("pass_through")
def tumble_passage(engine: Any, mover: Any, occupant: Any) -> str | None:
    condition = tumble_permission(mover, occupant.entity_id)
    if condition is not None:
        # Public test commentary omitted.
        # Public test commentary omitted.
        # Public test commentary omitted.
        if condition.data.get("entered") and not (
                set(engine._actor_volume(mover)) & set(engine._actor_volume(occupant))):
            return None
        return "difficult"
    return None


def record_tumble(engine: Any, actor: Any, condition: Any, **changes: int) -> None:
    """Update the existing instance through its evented wire shape; all values are integers/strings."""
    condition.data.update(changes)
    engine._append_event("CONDITION_APPLIED", TUMBLE_SOURCE, actor_id=actor.entity_id,
        target_ids=(actor.entity_id,), payload={"condition_id": condition.condition_id,
        "instance_id": condition.instance_id, "source_actor_id": condition.source_actor_id,
        "expires_on": condition.expires_on, "data": dict(condition.data)})


@hook("pass_through_entered")
def tumble_entered(engine: Any, mover: Any, occupant: Any, intent: Any) -> None:
    condition = tumble_permission(mover, occupant.entity_id)
    if condition is not None and not condition.data.get("entered"):
        record_tumble(engine, mover, condition, entered=1)


@hook("movement_step")
def tumble_crossed(engine: Any, mover: Any, previous: Any, nxt: Any, intent: Any) -> None:
    for condition in list(mover.conditions.values()):
        if condition.condition_id != TUMBLE_PERMISSION or not condition.data.get("entered") or condition.data.get("left"):
            continue
        target = engine.state.actors.get(condition.data.get("target_id"))
        if target is None:
            continue
        occupied = set(engine._actor_volume(target))
        if occupied & set(engine._actor_volume(mover, previous)) and not occupied & set(engine._actor_volume(mover, nxt)):
            record_tumble(engine, mover, condition, left=1)
            if owns(engine, mover, "sudden_flank"):
                value = f"ADVANTAGE:{target.entity_id}"
                for mid, modifier in list(mover.modifiers.items()):
                    if modifier.source_definition_id == SUDDEN_FLANK and modifier.target_field == "attack_mode_vs" and modifier.value == value:
                        del mover.modifiers[mid]
                        engine._append_event("MODIFIER_REMOVED", SUDDEN_FLANK, actor_id=mover.entity_id,
                            target_ids=(mover.entity_id,), payload={"modifier_id": mid, "reason": "REPLACED"})
                engine._add_modifier(mover, SUDDEN_FLANK, "attack_mode_vs", "SET", value,
                                     "NEXT_ATTACK", expires_on="END_OF_CURRENT_TURN")
                note(engine, SUDDEN_FLANK, mover,
                     f"Sudden Flank: your next attack against {target.display_name} this turn has Advantage.", (target,))


@hook("button_description", priority=-10)
def tumble_help(row: dict[str, Any]) -> str | None:
    typed = (row.get("parameters") or {}).get("typed") or {}
    if any(e.get("type") == "athletics_tumble" for e in typed.get("effects") or ()):
        economy = "Bonus Action" if row.get("economy") == "BONUS_ACTION" else "Action"
        return (f"{economy}: make a Dexterity (Acrobatics) check against a visible enemy within 5 feet "
                "making its own Dexterity (Acrobatics) check. If you win, move through that enemy's space "
                "once this turn, using your movement. "
                "Its space is difficult terrain; you cannot stop there. No Martial Focus cost.")
