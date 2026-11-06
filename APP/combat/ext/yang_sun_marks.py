"""Yang's mark expression, Completing Flame Mantle, Life Refuses Closure, Dawn Commands the
Fallen Breath, and Ten-Thousand Motions Become Noon.

One plug-in per source record family, wired only through documented hooks/effects
(combat/ext/__init__.py); it is inert for a character that owns none of these records.

``mark_apply`` (TAL_YANG_KINDLED_AND_OVERKINDLED_MARKS)
    Enforces the printed expression: a Rising Mark on the marker or a willing creature is a
    Kindled Mark; the same mark on an unwilling creature is an Overkindled Mark. Each producer
    already names its mark, so this hook only replaces a name the bearer's willingness
    contradicts. The recipient answers through the shared willing-target consent transport.
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
    condition with integer/string data only. A positive DAMAGE_COMMITTED receipt consumes
    Life's first occurrence; confirmed_attack_roll_bonus and settled_save_roll_bonus consume Dawn's first
    hit/failed save. The recipient may choose the compiled Complete Force effect (including
    Mantle) or Dawn's Complete Aim path, without taking the owner's round slot. Declining
    consumes the occurrence, not the mark; pending prompts replay transactionally.
``ally_row_allowed`` (TAL_YANG_LIFE_REFUSES_CLOSURE)
    "but not killed outright": a hit whose leftover damage would kill the creature instantly
    cannot be turned into "drops to 1 Hit Point" by Life Refuses Closure.
``turn_start_choice`` / ``after_move`` / ``zone_created`` (TAL_YANG_TEN_THOUSAND_MOTIONS_BECOME_NOON)
    The area's start-of-turn marks (an ally may gain one Kindled Mark; an enemy that starts
    its turn Hidden, Invisible, heavily obscured or under an illusion gains one Overkindled
    Mark) and its twenty-foot movement light. ``roll_response_die`` gives one response die its
    maximum result when the marker spends a Rising Mark while inside the area (used by
    all roll-based responses, including Complete Aim, Force, Resolve and Overheat Force).

Illumination itself (bright/dim radius, and "not sunlight") is presentation data only: the
engine does not track light levels, which is why the moved creature's light is recorded as a
plain condition pill and the zone's bright 10-foot radius stays in its visual profile.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from . import effect, hook

EXPRESSION = 'TAL_YANG_KINDLED_AND_OVERKINDLED_MARKS'
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


def _willing(ctx: Any, bearer: Any) -> bool:
    """Self is willing; other bearers answer using the engine's recipient consent policy."""
    marker = ctx.actor
    if bearer.entity_id == marker.entity_id:
        return True
    from .willing_targets import asks_consent

    action_name = ctx.action.display_name
    return asks_consent(
        ctx.engine, ctx.intent, bearer, action_name,
        f'{marker.display_name} uses {action_name} on {bearer.display_name}: accept a Rising Mark? '
        'Accept to gain a Kindled Mark that can help complete an action and that you may end '
        'at any time, no Action required. Refuse to gain an Overkindled Mark instead; '
        'it can strain hostile exertion and cannot be ended this way. No Action or CP cost to answer.',
        prefer_accept=bearer.team_id == marker.team_id, asker=marker)


# ------------------------------------------------------------------ mark expression
@hook('compile_passives')
def expression_ownership(passives: list[dict[str, Any]], info: dict[str, Any]) -> list[dict[str, Any]]:
    """Seal ownership of the expression record; a Yang producer alone does not grant it."""
    if EXPRESSION not in (info.get('owned_ids') or ()):
        return passives
    return [*passives, {'feature_id': EXPRESSION, 'block': 'yang_mark_expression'}]


@hook('mark_apply')
def expression(ctx: Any, effect_row: dict[str, Any], subject: Any, expires: Any, data: Any) -> bool | None:
    """Give a neutral "Rising Mark" the expression its bearer's willingness prints.

    An owning record that already names Kindled or Overkindled (Kindle the Wounded Breath's chosen
    target, Rising Thread's hit) keeps the name it wrote; this hook only resolves the base record's
    neutral "apply a Rising Mark".
    """
    name = str(effect_row.get('mark') or '').strip()
    producer = str(ctx.effect_source or ctx.typed.get('source')
                   or ((ctx.action.parameters or {}).get('typed') or {}).get('source') or ctx.source)
    yang_source = producer.startswith(('TAL_YANG_', 'tianxia.talent.yang.'))
    if (subject is None or name.lower() != 'rising mark' or not yang_source
            or not _owned(ctx.engine, ctx.actor, EXPRESSION)):
        return None
    wanted = KINDLED if _willing(ctx, subject) else OVERKINDLED
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
                     if a.active and a is not owner
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
    from .willing_targets import asks_consent

    if not asks_consent(
            ctx.engine, ctx.intent, ally, 'Completing Flame Mantle',
            f'Completing Flame Mantle: {owner.display_name} used Kindle the Rising on itself. '
            f'Accept a Kindled Mark on {ally.display_name} until the end of {owner.display_name}’s next turn? '
            'It can help complete an action and costs no Action or CP. Refusing gives no linked mark.',
            prefer_accept=ally.team_id == owner.team_id, asker=owner):
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
        if posture.standing_cost(ctx.engine, subject, cost=0) is None:
            continue
        from . import needle

        picked = needle.ask(
            ctx.engine, ctx.intent, needle.checkpoint_id(ctx.engine, 'dawn_stand', subject.entity_id),
            subject, 'choice:needle.dawn_stand', ['stand'], allow_decline=True,
            labels={'stand': 'Stand up now, without spending movement'},
            name='Dawn Commands the Fallen Breath', feature_id=DAWN,
            prompt=f'Dawn Commands the Fallen Breath prevents {subject.display_name} from dying. '
                   'Stand up now? This costs no movement, Action or CP; you may stay prone instead.')
        if picked:
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


def offer_completion(engine: Any, bearer: Any, target: Any, intent: Any, source_id: Any,
                     kind: str, *, saving_throw: bool = False) -> int | None:
    """Resolve the exception at its first qualifying occurrence, even when declined.

    Removal is transactional: an unanswered table prompt rolls it back, so replay
    asks the same question. Accepted Force uses the owner's compiled effect path,
    including Mantle and Noon, rather than a second damage-dice implementation.
    """
    condition = _exception_on(engine, bearer)
    if condition is None or (condition.data or {}).get('kind') != kind:
        return
    owner = engine.state.actors.get((condition.data or {}).get('owner'))
    source = str((condition.data or {}).get('source') or EXCEPTION)
    engine._remove_condition(bearer, EXCEPTION, source)
    if owner is None or not owner.active:
        return
    from ..typed_executor import bears_mark, block_spend_mark, run_effects
    from . import needle
    from .states import context

    if not bears_mark(bearer, owner.entity_id, 'Kindled Mark'):
        return
    row = next((r for r in getattr(engine, 'typed_reaction_rows', {}).get(owner.entity_id, ()) or ()
                if str(r.get('feature_id')) == FORCE), None)
    if row is None:
        return
    options = ['force']
    labels = {'force': 'Complete Force: spend your Kindled Mark to add its bonus damage'}
    if kind == 'first_hit_or_save':
        options.append('aim')
        labels['aim'] = 'Complete Aim: spend your Kindled Mark for its completion die'
    picked = needle.ask(
        engine, intent, needle.checkpoint_id(engine, 'completion_force', bearer.entity_id),
        bearer, 'choice:needle.completion_force', options, labels=labels, allow_decline=True,
        target_id=target.entity_id, name='Complete Force / Complete Aim' if len(options) > 1 else 'Complete Force',
        feature_id=source,
        prompt=f'{source.replace("TAL_YANG_", "").replace("_", " ").title()}: '
               f'{bearer.display_name} used {engine.action_catalog[source_id].display_name if source_id in engine.action_catalog else "an effect"} '
               f'against {target.display_name}. This is its first qualifying occurrence. '
               'Spend its Kindled Mark on a completion response without using the Yang once-per-round limit? '
               'No Action or CP cost. Passing ends this exception, but keeps the mark.')
    if not picked:
        return
    inner = context(engine, owner, FORCE, [bearer], dict(row.get('numbers') or {}))
    inner.action = inner.action.model_copy(update={'source_definition_id': FORCE, 'display_name': 'Complete Force'})
    inner.effect_source = FORCE
    inner.intent = intent
    if picked[0] == 'aim':
        from .yang_recovery import complete_aim_exception

        aim_ctx = context(engine, bearer, str(source_id), [target])
        aim_ctx.intent = intent
        return complete_aim_exception(aim_ctx, bearer, target, owner, saving_throw=saving_throw)
    block_spend_mark(inner, {'mark': 'Kindled Mark', 'applies_to': 'target'})
    inner = replace(inner, targets=[target], target=target)
    run_effects(inner, [{**entry, 'applies_to': 'target'} for entry in row.get('effects') or ()
                        if entry.get('type') != 'spend_mark'])


@hook('confirmed_attack_roll_bonus')
def exception_complete_force(engine: Any, attacker: Any, target: Any, spec: Any, intent: Any, source_id: Any) -> int | None:
    """Dawn qualifies only after a hit is confirmed, never at pre-roll Aim."""
    return offer_completion(engine, attacker, target, intent, source_id, 'first_hit_or_save')


@hook('state_event')
def first_damage_completion(engine: Any, event: Any) -> None:
    """Life observes actual positive damage, including native and non-attack packets."""
    if event.event_type != 'DAMAGE_COMMITTED' or not event.actor_id or not event.target_ids:
        return
    if int(event.payload.get('hp_damage') or 0) + int(event.payload.get('temporary_hp_absorbed') or 0) <= 0:
        return
    bearer = engine.state.actors.get(event.actor_id)
    target = engine.state.actors.get(event.target_ids[0])
    if bearer is not None and target is not None:
        offer_completion(engine, bearer, target, getattr(engine, '_active_intent', None),
                         event.source_definition_id, 'first_damage')


@hook('settled_save_roll_bonus')
def first_failed_save_completion(engine: Any, subject: Any, ability: Any, dc: int,
                                roll: Any, source_id: str, intent: Any, failed: bool,
                                bearer: Any) -> int | None:
    """Dawn subtracts Aim only after the save's final outcome is settled."""
    if failed and bearer is not None:
        bonus = offer_completion(engine, bearer, subject, intent, source_id,
                                 'first_hit_or_save', saving_throw=True)
        return -bonus if bonus else None


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
    from ..spatial_areas import zone_contains
    from ..gate2_runtime_models import Position
    movements = []
    for event in reversed(engine.events):
        if event.actor_id != subject.entity_id:
            continue
        if event.event_type == 'TURN_STARTED':
            break
        if event.event_type == 'MOVEMENT_COMMITTED' and not (
                (event.payload or {}).get('forced') or (event.payload or {}).get('teleport')):
            movements.append(event)
    from .effect_durations import token
    from .condition_ownership import refresh_owned
    from . import needle

    for zone in _in_noon(engine, subject):
        owner = engine.state.actors.get(zone.owner_id)
        if owner is None or not owner.active or not _owned(engine, owner, NOON):
            continue
        distance = 0
        for event in movements:
            path = [Position.model_validate(point) for point in event.payload.get('path') or []]
            for start, end in zip(path, path[1:]):
                if (zone_contains(engine, subject, zone, at=start)
                        and zone_contains(engine, subject, zone, at=end)):
                    distance += engine.grid.square_size_ft
        if distance < 20:
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
    """Use the same effective amount-roll path as typed response effects."""
    from ..effect_rolls import roll_amount

    return roll_amount(engine, owner, spec, reason.split(':', 1)[-1], reason)


@hook('amount_roll')
def noon_response_die(engine: Any, owner: Any, source: str, spec: Any, roll: Any) -> Any:
    """Noon increases ONE die, not the entire pool, for every dice-bearing response."""
    responses = (
        FORCE, 'TAL_YANG_KINDLED_RESPONSES#complete_aim',
        'TAL_YANG_KINDLED_RESPONSES#complete_resolve',
        'TAL_YANG_OVERKINDLED_RESPONSES#overheat_force',
    )
    if not any(str(source).endswith(response) for response in responses):
        return None
    if not roll.dice or not any(zone.owner_id == owner.entity_id for zone in _in_noon(engine, owner)):
        return None
    # The creature spending the mark must be in the area, not necessarily the bearer.
    if not _owned(engine, owner, NOON):
        return None
    values = (int(spec.sides), *roll.dice[1:])
    return roll.model_copy(update={'dice': values,
                                   'total': roll.total + int(spec.sides) - roll.dice[0]})
