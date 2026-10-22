"""Flood the Battlefield: the caster's own Court, the chosen flood roster, and Water-only check pressure.

Printed (Water, Flood the Battlefield): "While your Court of the Endless Tide is active, you may
spend 3 CP as an action to flood it. Until the start of your next turn, the Domain becomes
waist-deep spiritual floodwater for creatures of your choice. Hostile creatures without Swim Speed
treat the area as Difficult Terrain and have Disadvantage on Strength and Dexterity checks made to
resist your Water effects. When you activate the flood, choose up to a number of hostile creatures
equal to your Proficiency Bonus. Each makes a Strength saving throw. On a failure, a creature is
knocked Prone, moved 30 feet into a legal space, and suffers Drowning Pressure until the end of its
next turn. On a success, it is moved 10 feet and becomes Soaked."

The review findings are answered here, each on a seam the engine already documents.

1. Own active Court (candidate_allowed / candidate_unavailability). ``activation.trigger`` names the
   Court but is display text, so nothing read it and the option was offered with no Court active. The
   Court is a live, active zone owned by this caster, which is exactly what
   ``water_tide_footwork.courts`` already asks, so this reuses that one published query rather than
   adding a second Court test. Default-inert: any caster without an active Court is offered nothing.

2. The Disadvantage is scoped to checks resisting THIS CASTER's Water effects (ability_check_mode).
   The reviewed row records an unqualified ``disadvantage`` effect and ``block_advantage`` writes a bare
   ``check_mode`` rule that every later Strength/Dexterity check reads, so a creature the flood touched
   used to have Disadvantage on unrelated Strength and Dexterity checks. This compiles that clause into
   a scoped marker instead and answers the documented ``ability_check_mode`` seam, which ``check_modes``
   asks whenever the check names an opposing creature and needs no hazard tag -- exactly "a Strength or
   Dexterity check made to resist your Water effects". The check's source must also be a Water action
   the caster owns (check metadata, else the action being resolved): a Shove or Lift made against the
   same caster is not a Water effect and keeps its ordinary mode. Every other ability keeps the
   unqualified path.

3. Swim Speed is a general, published query (combat/swim_speed.py), not a Flood special case. The
   rider says "Hostile creatures without Swim Speed treat the area as Difficult Terrain", but the
   runtime models carry only walking, flying and climbing speed. This module publishes
   ``swim_speed_ft``, a pure per-creature lookup any ability may use, plus a ``swim_speed`` plug-in
   hook documented in ext/__init__.py. No core actor field is added and no other ability's behaviour
   changes: with no subscriber every creature reports no Swim Speed, exactly as today. The exemption
   itself answers ``difficult_zone_exempt`` for both areas that carry the clause: the flooded Court and
   the Flood's own 60-foot emanation.

4. The printed displacements are mandatory, so no distance is chosen. "Moved 30 feet into a legal
   space" and "it is moved 10 feet" are not "up to"; the ``forced_movement_distance`` seam is
   documented for optional pushes only (ext/__init__.py), so Flood does not answer it. The engine's
   own typed ``forced_movement`` row moves the creature the full printed distance, stopping at the
   last legal space and applying any printed restriction or reduction, and nothing here offers a
   "do not move it" option.

Drowning Pressure keeps the printed deadline already reviewed for it: "until the end of its next
turn" is ``until_end_of_next_turn``, which ``duration_turns`` anchors to the HOLDER, so the pressure
ends at the end of the VICTIM's next turn and not the caster's. That mapping is native and is not
changed here; the regression covers it.

Cost: the printed line is "you may spend 3 CP as an action to flood it" -- an optional 3 CP payment.
The reviewed row already carries ``cp``/3 and the compiler's own mapping resolves a printed ``cp``
cost through the character's Path pool ("CP means the character's current Path resource"), so a Qi
character pays it as 3 Qi. No cost data changes here.
"""

from __future__ import annotations

from typing import Any

from . import effect, hook
from ..swim_speed import swim_speed_ft
from .water_tide_footwork import courts

FLOOD = 'TAL_WATER_FLOOD_THE_BATTLEFIELD'
COURT = 'TAL_WATER_COURT_OF_THE_ENDLESS_TIDE'
FLOOD_MARK = 'condition:typed.mark.floodwater.'
WATER_SPHERE = 'tianxia.sphere.water'


def flood_typed(action: Any) -> dict[str, Any] | None:
    """The typed payload of a compiled Flood action, or None for every other action."""
    if action is None:
        return None
    typed = (getattr(action, 'parameters', None) or {}).get('typed') or {}
    return typed if typed.get('source') == FLOOD else None


@hook('candidate_allowed')
def needs_own_active_court(engine: Any, actor: Any, candidate: Any, action: Any):
    """Flood is offered only while this caster's own Court is actually active."""
    if flood_typed(action) is None:
        return None
    return None if next(courts(engine, actor), None) is not None else False


@hook('candidate_unavailability')
def explains_missing_court(engine: Any, actor: Any, candidate: Any, action: Any) -> str | None:
    """Say why Flood is off the menu, in the plain words of the printed Trigger."""
    if flood_typed(action) is None or next(courts(engine, actor), None) is not None:
        return None
    return ('Flood the Battlefield works only while your own Court of the Endless Tide is active, and '
            'yours is not active right now.')


@hook('compile_action')
def scope_water_pressure(action: Any, info: dict[str, Any]) -> Any:
    """Replace Flood's unqualified Disadvantage with a Water-only, caster-scoped marker.

    The reviewed ``disadvantage`` row is dropped from THIS action's effect list and the same clause is
    appended as ``water_pressure``, which ``apply_water_pressure`` below executes. Every other action
    keeps the ordinary, unqualified Disadvantage path unchanged.
    """
    typed = flood_typed(action)
    if typed is None:
        return None
    effects = typed.get('effects') or []
    kept = [row for row in effects
            if not (row.get('type') == 'disadvantage' and row.get('applies_to') == 'enemies_in_area')]
    if len(kept) == len(effects):
        return None
    scoped = dict(typed)
    scoped['effects'] = [*kept, {
        'type': 'water_pressure', 'applies_to': 'enemies_in_area', 'abilities': ['STR', 'DEX'],
        'mode': 'DISADVANTAGE',
        'evidence': 'have Disadvantage on Strength and Dexterity checks made to resist your Water effects'}]
    return action.model_copy(update={'parameters': {**action.parameters, 'typed': scoped}})


def flooded_by(actor: Any, owner_id: str) -> bool:
    """Whether ``actor`` carries a floodwater marker this caster wrote."""
    # Instance keys are 'condition-instance:<condition_id>:...', so match the condition id itself.
    return any(str(c.condition_id).startswith(FLOOD_MARK) and (c.data or {}).get('flood_owner') == owner_id
               for c in getattr(actor, 'conditions', {}).values())


@effect('water_pressure')
def apply_water_pressure(ctx: Any, spec: dict[str, Any]) -> None:
    """Mark each flooded creature so only checks resisting this caster are pressured, and flood the Domain.

    The marker carries the caster's entity id, so one caster's flood never presses another caster's
    checks, and it expires on the printed duration (until the start of the owner's next turn).
    Recipients are resolved with the engine's own published ``default_subjects``, exactly as the
    unqualified disadvantage effect it replaces did, so the chosen hostile roster is the same one.

    The Court's own printed rider is that "The Domain does not fill the entire area with physical water
    unless you use talents that create floodwater", so an unflooded Court is NOT difficult. This effect
    is that talent, and it is the only thing here that turns the Court into difficult ground, for the
    printed window only; ``clear_flood_terrain`` restores it at the deadline.
    """
    from ..typed_executor import default_subjects, effect_expiry

    owner = ctx.actor
    subjects = default_subjects(ctx, spec, harmful=False)
    if not subjects:
        subjects = [t for t in (list(ctx.targets) + ([ctx.target] if ctx.target else [])) if t is not None]
    for subject in subjects:
        ctx.engine._apply_condition(
            subject, FLOOD_MARK + owner.entity_id, ctx.source, owner.entity_id,
            expires_on=effect_expiry(ctx, spec, subject, condition=True) or 'UNTIL_REMOVED',
            data={'flood_owner': owner.entity_id,
                  'label': 'Standing in floodwater: Strength and Dexterity checks it makes to resist this '
                           "Water user's Water effects are at Disadvantage."})
    flood_terrain(ctx.engine, owner)


def flood_terrain(engine: Any, owner: Any) -> None:
    """Make this caster's Court difficult for hostiles while the flood lasts.

    Sets the zone's own ``difficult`` policy, the same recorded-zone seam Icefall Lattice uses. Only a
    Court's difficulty is written, only for its own owner, and only while a Flood is active; an
    unflooded Court keeps its printed "does not fill the area with physical water" behaviour.
    """
    for zone in courts(engine, owner):
        zone.trigger_profile['difficult'] = 'hostile'
        zone.trigger_profile['flooded_by'] = owner.entity_id
        engine._append_event('ZONE_CREATED', FLOOD, actor_id=owner.entity_id,
                             payload={'zone': zone.model_dump(mode='json')})


@hook('turn_start')
def clear_flood_terrain(engine: Any, actor: Any) -> None:
    """The floodwater is gone at the start of the caster's next turn, so the ground is ordinary again.

    An unflooded Court's difficulty is never restored, because nothing set it: a Court that was not
    flooded keeps its own printed behaviour throughout.
    """
    for zone in courts(engine, actor):
        if zone.trigger_profile.get('flooded_by') == actor.entity_id:
            zone.trigger_profile.pop('difficult', None)
            zone.trigger_profile.pop('flooded_by', None)
            engine._append_event('ZONE_CREATED', FLOOD, actor_id=actor.entity_id,
                                 payload={'zone': zone.model_dump(mode='json')})


@hook('ability_check_mode')
def water_only_pressure(engine: Any, actor: Any, ability: Any, skill: Any, against: Any):
    """Disadvantage only on checks made to resist THIS caster's Water effects.

    Three things must hold: the check is Strength or Dexterity; it is made against the caster who
    flooded this creature; and the check's own source is a Water action that caster owns. The source is
    the explicit check metadata when given, otherwise the action being resolved. A Strength or Dexterity
    check made under another sphere against the same caster (a Brutal Shove, a Lift) keeps its ordinary
    mode, because it is not a Water effect. Default-inert with no floodwater marker.
    """
    if against is None or str(ability or '').upper() not in {'STR', 'DEX'}:
        return None
    if not flooded_by(actor, getattr(against, 'entity_id', None)):
        return None
    return 'DISADVANTAGE' if check_is_water_effect(engine, actor, against) else None


def check_is_water_effect(engine: Any, actor: Any, owner: Any) -> bool:
    """Whether the check being made is one of `owner`'s Water effects.

    The source action must be filed under the Water sphere and must belong to `owner`.
    """
    from ..check_context import current
    source_id = str(current(engine, actor).get('source_id') or getattr(engine, '_active_action_source_id', '') or '')
    action = engine.action_catalog.get(source_id)
    if action is None or action.owner_id != owner.entity_id:
        return False
    return str(((action.parameters or {}).get('typed') or {}).get('sphere') or '') == WATER_SPHERE


@hook('difficult_zone_exempt')
def floodwater_is_difficult(engine: Any, actor: Any, zone: Any):
    """Hostile creatures WITHOUT Swim Speed treat flooded ground as Difficult Terrain.

    Two areas carry the printed clause: the caster's flooded Court, and the Flood's own 60-foot
    emanation, which the compiler gives a ``difficult: hostile`` zone because the rider says so. A
    creature that swims is excused from either, using the general Swim Speed query every rider shares
    rather than a Flood-only test. The Court is charged only while a floodwater marker its own owner
    wrote is live ("for creatures of your choice"), so an unflooded Court adds nothing here.
    """
    action = engine.action_catalog.get(getattr(zone, 'source_definition_id', ''))
    typed = (action.parameters.get('typed') or {}) if action else {}
    if typed.get('source') == FLOOD:
        return True if swim_speed_ft(engine, actor) else None
    if getattr(zone, 'owner_id', None) is None or typed.get('source') != COURT:
        return None
    if not flooded_by(actor, zone.owner_id):
        return None
    return True if swim_speed_ft(engine, actor) else None
