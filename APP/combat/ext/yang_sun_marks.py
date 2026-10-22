"""Yang's mark expression, Completing Flame Mantle, Life Refuses Closure, Dawn Commands the
Fallen Breath, and Ten-Thousand Motions Become Noon.

One plug-in per source record family, wired only through documented hooks/effects
(combat/ext/__init__.py); it is inert for a character that owns none of these records.

``mark_apply`` (TAL_YANG_KINDLED_AND_OVERKINDLED_MARKS)
    Enforces the printed expression: a Rising Mark on the marker or a willing creature is a
    Kindled Mark; the same mark on an unwilling creature is an Overkindled Mark. Each producer
    already names its mark, so this hook only replaces a name the bearer's willingness
    contradicts. Willingness follows the table's own team relationship.
``additional_actions`` / ``candidate_allowed`` / ``effect('yang_end_rising_mark')``
    The printed "a willing creature may end your Rising Mark on itself at any time, no Action
    required", as a NONE-economy button offered only to a bearer of a Kindled (not
    Overkindled) Rising Mark.
``mark_applied`` (TAL_YANG_COMPLETING_FLAME_MANTLE)
    "when you use Kindle the Rising on yourself, you may also apply a Kindled Mark to one
    willing creature within 10 feet", offered only while this owner's Mantle area is active.
``compile_reaction`` + ``effect('yang_completion_damage')``
    "once per turn when you spend a Kindled Mark with Complete Force, the bonus damage may be
    Fire, Radiant, or Force damage instead": the owned Complete Force row's damage is wrapped
    and the owner chooses one of the three while the Mantle is active. Without an active
    Mantle the row keeps its ordinary untyped bonus.
``compile_reaction`` + ``effect('yang_immediate_stand')`` / ``effect('yang_completion_exception')``
    Dawn's "It may immediately stand if Prone" and the first-damage/first-hit exception of
    Life Refuses Closure and Dawn Commands the Fallen Breath. The exception is a stored
    condition with integer/string data only; ``confirmed_hit_roll_bonus`` asks its bearer and,
    on a yes, spends the Kindled Mark and adds the Complete Force dice without taking the
    Yang owner's once-per-round response slot (``completion_allows``/``consume_completion``
    are also read by yang_recovery's Complete Aim checkpoint).
``ally_row_allowed`` (TAL_YANG_LIFE_REFUSES_CLOSURE)
    "but not killed outright": a hit whose leftover damage would kill the creature instantly
    cannot be turned into "drops to 1 Hit Point" by Life Refuses Closure.
``turn_start_choice`` / ``after_move`` / ``zone_created`` (TAL_YANG_TEN_THOUSAND_MOTIONS_BECOME_NOON)
    The area's start-of-turn marks (an ally may gain one Kindled Mark; an enemy that starts
    its turn Hidden, Invisible, heavily obscured or under an illusion gains one Overkindled
    Mark) and its twenty-foot movement light. ``roll_response_die`` gives one response die its
    maximum result when the marker spends a Rising Mark while inside the area (used by
    yang_recovery's Complete Aim roll; other responses' dice have no maximum-result seam yet).

Illumination itself (bright/dim radius, and "not sunlight") is presentation data only: the
engine does not track light levels, which is why the moved creature's light is recorded as a
plain condition pill and the zone's bright 10-foot radius stays in its visual profile.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from . import effect, hook

MANTLE = 'TAL_YANG_COMPLETING_FLAME_MANTLE'
LIFE = 'TAL_YANG_LIFE_REFUSES_CLOSURE'
DAWN = 'TAL_YANG_DAWN_COMMANDS_THE_FALLEN_BREATH'
NOON = 'TAL_YANG_TEN_THOUSAND_MOTIONS_BECOME_NOON'
FORCE = 'TAL_YANG_KINDLED_RESPONSES#complete_force'
KINDLE = 'TAL_YANG_APPLYING_A_RISING_MARK#kindle_the_rising'
# Per-owner catalog id: "system:combat.yang_end_rising_mark:<owner entity id>". A fixed id collided
# (TYPED_ACTION_ID_COLLISION) as soon as two Kindle owners shared one engine.
CANCEL = 'system:combat.yang_end_rising_mark'
EXCEPTION = 'condition:typed.yang_completion_exception'
DIM_LIGHT = 'condition:typed.yang_noon_dim_light'
MARK_PREFIX = 'condition:typed.mark.'

KINDLED = 'kindled mark'
OVERKINDLED = 'overkindled mark'
RISING = KINDLED, OVERKINDLED, 'rising mark'
DISPLAY = {KINDLED: 'Kindled Mark', OVERKINDLED: 'Overkindled Mark', 'rising mark': 'Rising Mark'}


def _owned(engine: Any, actor: Any, mechanic_id: str) -> bool:
    """Whether this actor's own compiled catalog carries the record (action, reaction or passive)."""
    if actor is None:
        return False
    for action in (engine.action_catalog or {}).values():
        if action.owner_id != actor.entity_id:
            continue
        typed = (action.parameters or {}).get('typed') or {}
        if typed.get('source') == mechanic_id or str(action.source_definition_id).endswith(mechanic_id):
            return True
    if any(str(row.get('feature_id')) == mechanic_id
           for row in getattr(engine, 'typed_reaction_rows', {}).get(actor.entity_id, ()) or ()):
        return True
    return any(str(row.get('feature_id')) == mechanic_id
               for row in getattr(engine, 'typed_passive_rows', {}).get(actor.entity_id, ()) or ())


def _mark_name(condition_id: str) -> str:
    body = str(condition_id).removeprefix(MARK_PREFIX)
    slug = body.split('.', 1)[0]
    return slug.replace('_', ' ')


def _mark_owner(condition_id: str) -> str:
    body = str(condition_id).removeprefix(MARK_PREFIX)
    return body.split('.', 1)[1] if '.' in body else ''


def _willing(marker: Any, bearer: Any) -> bool:
    """"willing creature" is the mark placer or a creature on its team; the table keeps no consent record."""
    return bearer.entity_id == marker.entity_id or bearer.team_id == marker.team_id


# ------------------------------------------------------------------ mark expression
@hook('mark_apply')
def expression(ctx: Any, effect_row: dict[str, Any], subject: Any, expires: Any, data: Any) -> bool | None:
    """Give a neutral "Rising Mark" the expression its bearer's willingness prints.

    An owning record that already names Kindled or Overkindled (Kindle the Wounded Breath's chosen
    target, Rising Thread's hit) keeps the name it wrote; this hook only resolves the base record's
    neutral "apply a Rising Mark".
    """
    name = str(effect_row.get('mark') or '').strip()
    if subject is None or name.lower() != 'rising mark':
        return None
    wanted = KINDLED if _willing(ctx.actor, subject) else OVERKINDLED
    from ..typed_executor import block_mark

    inner = replace(ctx, targets=[subject], target=subject)
    block_mark(inner, {**effect_row, 'mark': DISPLAY[wanted]})
    return True


# ------------------------------------------------------------------ willing self-cancellation
def cancel_id(owner_id: str) -> str:
    return f'{CANCEL}:{owner_id}'


def _cancel_owner(action_id: Any) -> str | None:
    text = str(action_id or '')
    return text[len(CANCEL) + 1:] if text.startswith(CANCEL + ':') else None


def _ending_marks(engine: Any, bearer: Any, owner: str | None = None) -> list[str]:
    """Instance ids of Rising Marks this creature may end: Kindled or still-neutral, never Overkindled.

    ``owner`` limits the answer to marks placed by that Yang owner (one button per owner).
    """
    found = []
    for instance_id, condition in bearer.conditions.items():
        if not str(condition.condition_id).startswith(MARK_PREFIX):
            continue
        if owner is not None and _mark_owner(condition.condition_id) != owner:
            continue
        name = _mark_name(condition.condition_id)
        if name in (KINDLED, 'rising mark'):
            if _owned(engine, engine.state.actors.get(_mark_owner(condition.condition_id)), KINDLE):
                found.append(instance_id)
    return sorted(found)


@hook('compile_actions')
def cancel_action(info: dict[str, Any]) -> list[Any] | None:
    """Publish the free self-cancellation action on the Yang mark owner's own catalog (it persists with the bundle)."""
    if KINDLE not in (info.get('owned_ids') or ()):
        return None
    from ..gate2_runtime_models import ActionDefinition

    return [ActionDefinition(
        source_definition_id=cancel_id(info['actor_id']), display_name='End a Kindled Mark on yourself', owner_id=info['actor_id'],
        economy='NONE', resolution_kind='TYPED', target_kind='SELF',
        parameters={'typed': {'effects': [{'type': 'yang_end_rising_mark', 'applies_to': 'self'}],
                              'numbers': {}, 'riders': []},
                    'description': 'End a Kindled Mark another Yang cultivator placed on you. '
                                   'It costs no Action, Bonus Action or Reaction and changes nothing else. '
                                   'An Overkindled Mark on an unwilling creature cannot be ended this way.'})]


@hook('additional_actions')
def offer_cancel(engine: Any, actor: Any) -> list[str]:
    owners = sorted({_mark_owner(actor.conditions[instance].condition_id) for instance in _ending_marks(engine, actor)})
    return [cancel_id(owner) for owner in owners if cancel_id(owner) in engine.action_catalog]


@hook('candidate_allowed')
def cancel_allowed(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    owner = _cancel_owner(action.source_definition_id) if action is not None else None
    if owner is not None:
        return bool(_ending_marks(engine, actor, owner))
    return None


@effect('yang_end_rising_mark', harmful=False)
def end_rising(ctx: Any, row: dict[str, Any]) -> None:
    from . import needle

    owner = _cancel_owner(getattr(ctx.action, 'source_definition_id', None))
    if owner is None:
        return
    ended = []
    for instance_id in _ending_marks(ctx.engine, ctx.actor, owner):
        condition = ctx.actor.conditions.get(instance_id)
        if condition is None:
            continue
        ctx.engine._remove_condition_instance(ctx.actor, instance_id, cancel_id(owner))
        ended.append(_mark_name(condition.condition_id))
    if ended:
        needle.say(ctx.engine, cancel_id(owner), ctx.actor,
                   f'{ctx.actor.display_name} ends {" and ".join(name.title() for name in ended)} on itself. '
                   'No Action was used.', (ctx.actor.entity_id,))


# ------------------------------------------------------------------ Completing Flame Mantle
def _active_zone(engine: Any, owner: Any, mechanic_id: str) -> Any:
    from .. import zones

    for zone in zones.typed_zones(engine):
        if not zone.active or zone.owner_id != owner.entity_id:
            continue
        profile = zone.trigger_profile or {}
        named = str((profile.get('source_profile') or {}).get('mechanic_id') or '')
        if named == mechanic_id or str(zone.source_definition_id).endswith(mechanic_id):
            return zone
    return None


@hook('mark_applied')
def mantle_linked_mark(ctx: Any, name: str, subject: Any) -> None:
    """Kindle the Rising on yourself also marks one willing creature within 10 feet while the Mantle lasts."""
    if str(name or '').strip().lower() != KINDLED or subject is None:
        return
    owner = ctx.actor
    if subject.entity_id != owner.entity_id or not _owned(ctx.engine, owner, MANTLE):
        return
    if KINDLE not in str(getattr(ctx, 'source', '')) and KINDLE not in str(
            (ctx.action.parameters or {}).get('typed', {}) if ctx.action else ''):
        return
    if _active_zone(ctx.engine, owner, MANTLE) is None:
        return
    from . import needle
    from .. import stealth
    from ..typed_executor import block_mark

    allies = sorted((a for a in ctx.engine.state.actors.values()
                     if a.active and a is not owner and a.team_id == owner.team_id
                     and ctx.engine._distance_actor_to_actor(owner, a) <= 10
                     and (needle.answerable(ctx.engine, owner) or stealth.sees(ctx.engine, owner, a))),
                    key=lambda a: a.entity_id)
    if not allies:
        return
    picked = needle.ask(ctx.engine, ctx.intent, needle.checkpoint_id(ctx.engine, 'mantle_link', owner.entity_id),
                        owner, 'choice:needle.mantle_link', [a.entity_id for a in allies], allow_decline=True,
                        labels={a.entity_id: f'Also give {a.display_name} a Kindled Mark until the end of your next turn (no extra cost)'
                                for a in allies},
                        name='Completing Flame Mantle', feature_id=MANTLE,
                        prompt='Completing Flame Mantle: you used Kindle the Rising on yourself. '
                               'Give one willing creature within 10 feet a Kindled Mark too? It costs no extra Action or CP.')
    if not picked:
        return
    ally = ctx.engine.state.actors.get(picked[0])
    if ally is None:
        return
    block_mark(replace(ctx, targets=[ally], target=ally),
               {'type': 'mark', 'mark': 'Kindled Mark', 'applies_to': 'target',
                'duration': {'kind': 'until_end_of_your_next_turn'}})
    needle.say(ctx.engine, MANTLE, owner,
               f'Completing Flame Mantle: {ally.display_name} also gains a Kindled Mark from {owner.display_name}.',
               (ally.entity_id,))


@hook('compile_reaction')
def force_mantle_damage(row: dict[str, Any], info: dict[str, Any]) -> dict[str, Any] | None:
    """Complete Force's bonus damage is selectable while the owner's Mantle is active; otherwise unchanged."""
    if str(row.get('feature_id') or '') != FORCE or MANTLE not in (info.get('owned_ids') or ()):
        return None
    effects = []
    for entry in row.get('effects') or ():
        if isinstance(entry, dict) and entry.get('type') == 'damage':
            entry = {**{k: v for k, v in entry.items() if k != 'type'}, 'type': 'yang_completion_damage'}
        effects.append(entry)
    return {**row, 'effects': effects, 'numbers': dict(row.get('numbers') or {})}


@effect('yang_completion_damage')
def completion_damage(ctx: Any, row: dict[str, Any]) -> None:
    """The Complete Force bonus, typed Fire/Radiant/Force while the Mantle is active."""
    from . import needle
    from ..typed_executor import block_damage

    kinds = ['FIRE', 'RADIANT', 'FORCE'] if _active_zone(ctx.engine, ctx.actor, MANTLE) is not None else []
    chosen = ''
    if kinds:
        target = ctx.target or next(iter(ctx.targets or []), None)
        picked = needle.ask(ctx.engine, ctx.intent, needle.checkpoint_id(ctx.engine, 'mantle_force_type', ctx.actor.entity_id),
                            ctx.actor, 'choice:needle.mantle_force_type', kinds, allow_decline=False,
                            labels={kind: kind.title() + ' damage' for kind in kinds},
                            name='Complete Force', feature_id=MANTLE,
                            target_id=getattr(target, 'entity_id', None),
                            prompt=f'Complete Force inside Completing Flame Mantle: choose Fire, Radiant or Force damage for '
                                   f'the bonus against {target.display_name if target is not None else "the target"}. '
                                   'This replaces the damage type of that bonus only; it costs nothing more.')
        chosen = picked[0] if picked else kinds[0]
    block_damage(ctx, {**row, 'type': 'damage', **({'damage_types': [chosen.lower()]} if chosen else {})})


# ------------------------------------------------------------------ Life / Dawn continuation
@hook('compile_reaction')
def closure_reaction(row: dict[str, Any], info: dict[str, Any]) -> dict[str, Any] | None:
    """Add the printed continuation to the owned Life/Dawn Reaction rows."""
    mechanic_id = str(row.get('feature_id') or '')
    if mechanic_id not in (LIFE, DAWN) or mechanic_id not in (info.get('owned_ids') or ()):
        return None
    effects = list(row.get('effects') or ())
    if mechanic_id == DAWN:
        # Printed: "gains a Kindled Mark that lasts for 1 minute"; the carried row said until removed.
        effects = [{**entry, 'duration': {'kind': 'minutes', 'amount': 1}}
                   if isinstance(entry, dict) and entry.get('type') == 'mark' else entry for entry in effects]
        effects.append({'type': 'yang_immediate_stand'})
    effects.append({'type': 'yang_completion_exception', 'source': mechanic_id, 'applies_to': 'ally'})
    return {**row, 'effects': effects, 'numbers': dict(row.get('numbers') or {})}


@effect('yang_immediate_stand', harmful=False)
def immediate_stand(ctx: Any, row: dict[str, Any]) -> None:
    """Dawn: "It may immediately stand if Prone" (no movement spent)."""
    from .. import posture
    from ..typed_executor import _default_subject

    # "ally" resolves to the protected creature on both the self and the bystander path; the
    # reaction context's target is the attacker whenever the reactor is the one dying.
    for subject in _default_subject(ctx, {'applies_to': 'ally'}, harmful=False):
        if posture.standing_cost(ctx.engine, subject, cost=0) is not None:
            posture.stand_up(ctx.engine, subject, source_id=DAWN, cost=0)


@effect('yang_completion_exception', harmful=False)
def completion_exception(ctx: Any, row: dict[str, Any]) -> None:
    """Store the first-damage/first-hit exception for the protected creature, until its next turn ends."""
    from .effect_durations import token
    from ..typed_executor import _default_subject

    source = str(row.get('source') or ctx.source)
    for subject in _default_subject(ctx, {'applies_to': 'ally'}, harmful=False):
        if subject is None or not subject.active:
            continue
        expiry = token('end', subject.entity_id, subject.turns_started + 1)
        ctx.engine._remove_condition(subject, EXCEPTION, source)
        ctx.engine._apply_condition(subject, EXCEPTION, source, ctx.actor.entity_id, expires_on=expiry,
                                    data={'owner': ctx.actor.entity_id, 'source': source, 'used': False,
                                          'kind': 'first_damage' if source == LIFE else 'first_hit_or_save',
                                          'label': ('Life Refuses Closure: the first time it deals damage it may spend its '
                                                    'Kindled Mark with Complete Force outside the Yang once-per-round limit'
                                                    if source == LIFE else
                                                    'Dawn Commands the Fallen Breath: the first time it hits or forces a failed save '
                                                    'it may spend its Kindled Mark with Complete Force or Complete Aim outside the '
                                                    'Yang once-per-round limit')})


def _exception_on(engine: Any, bearer: Any, wanted: str | None = None) -> Any:
    for instance_id, condition in bearer.conditions.items():
        if condition.condition_id != EXCEPTION or (condition.data or {}).get('used'):
            continue
        source = str((condition.data or {}).get('source') or '')
        kind = str((condition.data or {}).get('kind') or '')
        if wanted == 'aim' and kind != 'first_hit_or_save':
            continue
        if wanted == 'force' and source != LIFE and kind != 'first_hit_or_save':
            continue
        return condition
    return None


def completion_allows(engine: Any, owner: Any, bearer: Any, use: str) -> bool:
    """Public query for yang_recovery: may this marked creature's exception pay for one response now?"""
    condition = _exception_on(engine, bearer, use)
    owner_id = getattr(owner, 'entity_id', owner)
    return bool(condition is not None and (condition.data or {}).get('owner') == owner_id)


def consume_completion(engine: Any, owner: Any, bearer: Any, use: str) -> bool:
    """Mark the exception used; True when it paid, so the shared once-per-round slot stays free."""
    if not completion_allows(engine, owner, bearer, use):
        return False
    owner_id = getattr(owner, 'entity_id', owner)
    for instance_id, condition in list(bearer.conditions.items()):
        if condition.condition_id != EXCEPTION or (condition.data or {}).get('owner') != owner_id:
            continue
        engine._remove_condition(bearer, EXCEPTION, str((condition.data or {}).get('source') or EXCEPTION))
        break
    return True


@hook('confirmed_hit_roll_bonus')
def exception_complete_force(engine: Any, attacker: Any, target: Any, spec: Any, intent: Any, source_id: Any) -> int | None:
    """The stored first-hit exception: spend the Kindled Mark on Complete Force, outside the round limit."""
    condition = _exception_on(engine, attacker, 'force')
    if condition is None:
        return None
    owner = engine.state.actors.get((condition.data or {}).get('owner'))
    if owner is None or not owner.active or not _owned(engine, owner, FORCE):
        return None
    from ..typed_executor import bears_mark, block_spend_mark

    if not bears_mark(attacker, owner.entity_id, 'Kindled Mark'):
        return None
    from . import needle
    from .states import context
    from ..gate2_runtime_models import DiceSpec
    from factory_authoring.typed_mechanics import dice_for_cl

    row = next((r for r in getattr(engine, 'typed_reaction_rows', {}).get(owner.entity_id, ()) or ()
                if str(r.get('feature_id')) == FORCE), None)
    if row is None:
        return None
    effect = next((e for e in row.get('effects') or () if e.get('type') in ('damage', 'extra_damage')), {})
    dice = dice_for_cl(effect.get('dice_by_cl'), (row.get('numbers') or {}).get('cl')) or effect.get('dice') or {}
    count, sides = int(dice.get('count') or 0), int(dice.get('sides') or 0)
    if count <= 0 or sides <= 1:
        return None
    bonus = int((row.get('numbers') or {}).get('key_mod') or 0)
    picked = needle.ask(engine, intent, needle.checkpoint_id(engine, 'completion_force', attacker.entity_id),
                        attacker, 'choice:needle.completion_force', ['use'], allow_decline=True,
                        target_id=target.entity_id, name='Complete Force', feature_id=FORCE,
                        labels={'use': f'Spend your Kindled Mark: add {count}d{sides}+{bonus} to this hit, '
                                       'outside the Yang once-per-round limit'},
                        prompt=f'Complete Force: {attacker.display_name} is about to hit {target.display_name}. '
                               f'Spend the Kindled Mark {owner.display_name} gave it to add {count}d{sides}+{bonus} '
                               'damage to this hit? This does not use the Yang once-per-round response.')
    if not picked:
        return None
    inner = context(engine, owner, FORCE, [attacker], dict(row.get('numbers') or {}))
    inner.action = inner.action.model_copy(update={'source_definition_id': FORCE, 'display_name': 'Complete Force'})
    inner.intent = intent
    block_spend_mark(inner, {'mark': 'Kindled Mark', 'applies_to': 'target'})
    consume_completion(engine, owner, attacker, 'force')
    roll = engine.roller.roll(DiceSpec(count=count, sides=sides, modifier=bonus),
                              actor_id=attacker.entity_id, reason='COMPLETE_FORCE:' + FORCE)
    engine._record_roll(roll)
    engine._append_event('CHECK_ROLLED', FORCE, actor_id=attacker.entity_id, target_ids=(target.entity_id,),
                         payload={**roll.model_dump(mode='json'), 'purpose': 'Complete Force bonus'})
    return int(roll.total)


@hook('damage_context_pending_reaction_rank')
def life_not_killed_outright(engine: Any, reactor: Any, row: dict[str, Any], packet: Any, intent: Any) -> dict[str, Any] | None:
    """Life Refuses Closure protects a creature reduced to 0, not one killed outright.

    The pending packet is the general per-packet context of the drop-to-zero checkpoint
    (combat/pending_damage.prepare), so the boundary uses the same amount the reaction would
    answer. Leftover damage at or past current + maximum Hit Points is instant death.
    """
    if str(row.get('feature_id') or '') != LIFE:
        return None
    subject = engine.state.actors.get(getattr(packet, 'target_id', None))
    if subject is None:
        return None
    from ..damage_allocation import available_temporary_hp

    temp = available_temporary_hp(engine, subject, int(packet.amount), getattr(packet, 'source_actor_id', None))
    hp_loss = max(0, int(packet.amount) - int(temp))
    if hp_loss >= subject.current_hp + subject.maximum_hp:
        return {'allowed': False}  # killed outright: 1 Hit Point is not a possible outcome
    return None


# ------------------------------------------------------------------ Ten-Thousand Motions Become Noon
def _noon_zones(engine: Any) -> list[Any]:
    from .. import zones

    out = []
    for zone in zones.typed_zones(engine):
        if not zone.active:
            continue
        profile = zone.trigger_profile or {}
        named = str((profile.get('source_profile') or {}).get('mechanic_id') or '')
        if named == NOON or str(zone.source_definition_id).endswith(NOON):
            out.append(zone)
    return out


def _in_noon(engine: Any, actor: Any) -> list[Any]:
    from ..spatial_areas import zone_contains

    return [zone for zone in _noon_zones(engine) if zone_contains(engine, actor, zone)]


def _concealed_for_noon(engine: Any, actor: Any) -> bool:
    """Hidden, Invisible, heavily obscured, or under an illusion -- the printed Overkindled list."""
    from .. import stealth, zones

    if stealth.hidden(actor) or any(str(c.condition_id) == 'condition:typed.invisible' for c in actor.conditions.values()):
        return True
    if any('illusion' in str(c.condition_id) for c in actor.conditions.values()):
        return True
    for zone in zones.typed_zones(engine):
        profile = zone.trigger_profile or {}
        if not zone.active or profile.get('wall'):
            continue
        if not (profile.get('obscured') == 'heavy' or (profile.get('visual') or {}).get('darkness')):
            continue
        from ..spatial_areas import zone_contains
        if zone_contains(engine, actor, zone):
            return True
    return False


@hook('turn_start_choice')
def noon_start_of_turn(engine: Any, actor: Any) -> None:
    """Allies may gain a Kindled Mark; a concealed enemy gains an Overkindled Mark."""
    for zone in _in_noon(engine, actor):
        owner = engine.state.actors.get(zone.owner_id)
        if owner is None or not owner.active or not _owned(engine, owner, NOON):
            continue
        from ..typed_executor import block_mark

        if actor.team_id == owner.team_id:
            from . import needle
            picked = needle.ask(engine, None, needle.checkpoint_id(engine, 'noon_ally_mark', actor.entity_id),
                                actor, 'choice:needle.noon_ally_mark', ['use'], allow_decline=True,
                                name='Ten-Thousand Motions Become Noon', feature_id=NOON,
                                labels={'use': f'Gain a Kindled Mark from {owner.display_name} '
                                               '(until the end of its next turn; no Action or CP cost)'},
                                prompt=f'Ten-Thousand Motions Become Noon: {actor.display_name} starts its turn in '
                                       f'{owner.display_name}\'s area. Gain one Kindled Mark? It costs nothing.')
            if picked:
                block_mark(_marker_ctx(engine, owner, [actor], zone),
                           {'type': 'mark', 'mark': 'Kindled Mark', 'applies_to': 'target',
                            'duration': {'kind': 'until_end_of_your_next_turn'}})
        elif _concealed_for_noon(engine, actor):
            block_mark(_marker_ctx(engine, owner, [actor], zone),
                       {'type': 'mark', 'mark': 'Overkindled Mark', 'applies_to': 'target',
                        'duration': {'kind': 'until_end_of_your_next_turn'}})


def _marker_ctx(engine: Any, owner: Any, targets: list[Any], zone: Any):
    """A mark placer's own context; the area stays the named source."""
    from . import needle
    from .states import context
    inner = context(engine, owner, NOON, targets, needle.numbers_of(engine, owner))
    inner.action = inner.action.model_copy(update={'source_definition_id': NOON, 'display_name': 'Ten-Thousand Motions Become Noon'})
    return inner


@hook('after_move')
def noon_moved_light(engine: Any, subject: Any, moved_ft: int) -> None:
    """Twenty feet of movement inside the area lights the mover until its next turn starts."""
    if engine.state.current_actor_id != subject.entity_id or not _in_noon(engine, subject):
        return
    distance = 0
    for event in reversed(engine.events):
        if event.actor_id != subject.entity_id:
            continue
        if event.event_type == 'TURN_STARTED':
            break
        if event.event_type != 'MOVEMENT_COMMITTED' or (event.payload or {}).get('forced') or (event.payload or {}).get('teleport'):
            continue
        distance += max(0, len((event.payload or {}).get('path') or []) - 1) * engine.grid.square_size_ft
    if distance < 20:
        return
    from .effect_durations import token
    from .condition_ownership import refresh_owned
    from . import needle

    for zone in _in_noon(engine, subject):
        owner = engine.state.actors.get(zone.owner_id)
        if owner is None or not owner.active or not _owned(engine, owner, NOON):
            continue
        refresh_owned(engine, subject, DIM_LIGHT, owner.entity_id, NOON)
        engine._apply_condition(subject, DIM_LIGHT, NOON, owner.entity_id,
                                expires_on=token('start', subject.entity_id, subject.turns_started + 1),
                                data={'label': f'{owner.display_name}\'s Ten-Thousand Motions Become Noon: '
                                               f'{subject.display_name} moved 20+ feet in the area and emits dim light '
                                               'until the start of its next turn (illumination is shown as a note; '
                                               'the engine does not track light levels)'})
        needle.say(engine, NOON, owner, f'Ten-Thousand Motions Become Noon: {subject.display_name} emits dim light '
                                        'until the start of its next turn.', (subject.entity_id,))


def roll_response_die(engine: Any, owner: Any, spec: Any, reason: str) -> Any:
    """Roll one response die; inside the owner's Noon area it is increased to its maximum result.

    Public helper for yang_recovery's Complete Aim checkpoint (the one response die whose roll this
    codebase exposes to a plug-in). One die per spend: the shared Kindled Responses group already
    allows one response per round.
    """
    roll = engine.roller.roll(spec, actor_id=owner.entity_id, reason=reason)
    if getattr(spec, 'count', 0) == 1 and int(getattr(spec, 'sides', 0)) > 1 and _in_noon(engine, owner):
        sides, modifier = int(spec.sides), int(getattr(spec, 'modifier', 0) or 0)
        roll = roll.model_copy(update={'dice': (sides,), 'total': sides + modifier})
    return roll
