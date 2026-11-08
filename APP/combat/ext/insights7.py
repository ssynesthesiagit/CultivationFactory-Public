"""Restorative Circulation: one chosen recipient of your own Qi-powered healing each turn.

``authority/typed_mechanics/rules_text.json`` -> ``insight.restorative-circulation``.
Once during each of your turns, when a Qi-powered feature restores Hit Points to
one or more creatures, choose one recipient: its healing is increased by your
Proficiency Bonus. A recipient at maximum Hit Points after that healing instead
gains that many Temporary Hit Points. At CL12, a chosen target at 0 Hit
Points receives twice the Proficiency Bonus instead. The benefit applies once per
activation, never per healing die, target, pulse or repeated tick.

Three printed clauses are carried here:

* **Own Qi-powered feature.** The general ``healing_offered_bonus_from`` seam
  (documented in ``ext/__init__.py``) supplies the acting creature, the granting
  source definition id and the feature's sphere with the offer. This rider only
  qualifies when the healer is the Insight's owner, the owner is the current
  actor, the sphere is a Qi sphere and the allowance is unspent -- so another
  creature's heal, a non-Qi heal and a second activation all leave it inert.
* **Choose one recipient.** The printed text says "choose one recipient" with no
  side restriction, so a manual or Ask-me owner is asked through the shared
  Needle transport and may pick any recipient of the activation, including an
  enemy, or decline and keep the allowance for a later activation. An automatic
  or AI chooser keeps the beneficial same-side policy (an ally or itself, never
  an enemy) and only among the recipients this activation will actually heal.
* **"already at maximum Hit Points after the healing"** is resolved against the
  post-healing result, so a wounded recipient that reaches full health from the
  qualifying heal gains the Temporary Hit Points the printed fallback promises.
  The "instead" is preserved: a recipient already at maximum gains no extra
  healing, only the Temporary Hit Points.

The flat addition is applied before stored reductions and capping, which is
exactly the printed "increase the healing it receives" step.
"""
from typing import Any

from . import hook
from .passive_rows import known_level, row_of

FEATURE = 'insight.restorative-circulation'
BLOCK = 'restorative_circulation'
CHOSEN = '_restorative_circulation_recipient'
PENDING = '_restorative_circulation_pending'
PENDING_ACTIVATION = '_restorative_circulation_activation'
PENDING_SOURCE = '_restorative_circulation_source'
USED = '_restorative_circulation_used'

CHOICE = 'choice:insights7.restorative_circulation'

# The printed trigger is "a Qi-powered feature": a feature of a Qi sphere. Documented here once so the
# qualification is a single general test rather than a per-feature list.
QI_SPHERES = frozenset({'tianxia.sphere.qiweaving'})

OUTCOME = ('Once each of your turns, one recipient of your Qi-powered healing gains an additional '
           'Proficiency Bonus of healing; a recipient at full health after that healing gains that many '
           'Temporary Hit Points instead, and from CL12 a chosen target at 0 Hit Points gains twice that bonus')


@hook('compile_block')
def compile_rows(block, spec, row, numbers):
    if block != BLOCK:
        return None
    return [{**row, 'kind': 'healing_bonus', 'pb': int(numbers['pb']), 'player_outcome': OUTCOME}]


def owner_of(engine: Any) -> Any | None:
    """The owner whose turn this is, when it owns the Insight and may still spend it.

    The printed trigger is your own Qi-powered feature healing during your turn,
    so the current actor is the only owner that can qualify; no live sheet is
    consulted and an old fight gains no entitlement.
    """
    actor = engine.state.actors.get(engine.state.current_actor_id)
    if actor is None or not actor.active or actor.current_hp <= 0:
        return None
    if actor.turn_flags.get(USED):
        return None
    return actor if row_of(engine, actor.entity_id, BLOCK, 'healing_bonus') is not None else None


def qi_powered(sphere: Any, power_resources: tuple[str, ...] = ()) -> bool:
    """Qi-powered provenance is either a Qi sphere or an explicit Qi resource cost."""
    return str(sphere or '') in QI_SPHERES or 'resource:core.qi' in power_resources


def same_side(owner: Any, subject: Any) -> bool:
    """Automatic policy only: the beneficial recipients of this activation are allies and the owner."""
    return subject.entity_id == owner.entity_id or subject.team_id == owner.team_id


def recipients(engine: Any, owner: Any, first: Any, eligible: tuple[Any, ...] = ()) -> list[Any]:
    """Every creature this activation may heal, so a manual chooser sees the whole activation at once.

    The roster is the activation's own live recipients: the printed "one or more
    creatures" the same heal reaches. A recipient is included whether or not it
    is the subject currently being offered, so a dying ally can be chosen ahead
    of an earlier target in iteration order, and an enemy can be chosen
    deliberately by a player. The caller supplies the actual live effect-eligible
    roster after area geometry and effect-level exclusions; the offer itself is
    retained as a fallback for callers with no roster.
    """
    seen = []
    for actor in (eligible or (first,)):
        live = engine.state.actors.get(getattr(actor, 'entity_id', None))
        if live is actor and actor.active and all(actor is not other for other in seen):
            seen.append(actor)
    if first not in seen:
        seen.append(first)
    return seen


@hook('choice_options')
def choice_spec(engine: Any, intent: Any, checkpoint: str, reactor_id: str, choice_id: str,
                context: dict[str, Any]) -> dict[str, Any] | None:
    """One recipient, offered by name, on the shared Needle transport."""
    from .needle import option_spec
    return option_spec(choice_id, context, CHOICE)


def _select(engine: Any, owner: Any, subject: Any, eligible: tuple[Any, ...], action_name: str, source: str) -> Any | None:
    """The printed choice of one recipient, asked of the owner only when the owner answers questions.

    An automatic or AI chooser takes the best beneficiary of this offer and never an enemy, which is the
    same-side policy a beneficial rider takes without asking. A manual or Ask-me owner is asked over the whole
    activation's roster and may choose any recipient -- including an enemy, as the printed text allows -- or
    decline, keeping the allowance for a later activation.
    """
    from .needle import ask, checkpoint_id
    options = recipients(engine, owner, subject, eligible)
    ids = [actor.entity_id for actor in options]
    labels = {actor.entity_id: actor.display_name for actor in options}
    helpful = [actor.entity_id for actor in options if same_side(owner, actor)]
    picked = ask(engine, getattr(engine, '_active_intent', None),
                 checkpoint_id(engine, 'restorative_circulation', owner.entity_id, *ids), owner, CHOICE, ids,
                 labels=labels, minimum=1, maximum=1, allow_decline=True, automatic_options=helpful,
                 preferred=helpful[:1], name='Restorative Circulation',
                 prompt=f'Restorative Circulation during {action_name}: choose who receives the additional healing (or Temporary Hit Points '
                        'if already at full health); at cultivation level 12 or higher, a target at 0 Hit Points receives twice '
                        'your Proficiency Bonus. This uses your once-per-turn benefit.',
                 prompt_context={'source_definition_id': source, 'action_name': action_name,
                                 'action_actor_id': owner.entity_id}) or []
    if not picked or picked[0] not in ids:
        return None
    return engine.state.actors.get(picked[0])


@hook('healing_offered_bonus_from')
def offered_bonus(engine, subject, amount, *, consume, healer, source, sphere,
                  power_resources=(), eligible_recipients=(), action_name='', activation_id=''):
    """The printed increase, only for the owner's own Qi-powered feature, once per activation."""
    if not qi_powered(sphere, tuple(power_resources)):
        return None  # not a Qi-powered feature: the printed trigger never fires
    actor = engine.state.actors.get(engine.state.current_actor_id)
    if actor is None or not actor.active or actor.current_hp <= 0:
        return None
    owner = actor if row_of(engine, actor.entity_id, BLOCK, 'healing_bonus') is not None else None
    if owner is None or healer is None or healer.entity_id != owner.entity_id:
        return None  # another creature's heal, or a sheet without the Insight: nothing to qualify
    if subject.active is False or subject.current_hp < 0:
        return None
    continuation = (consume and subject.entity_id == owner.turn_flags.get(CHOSEN)
                    and activation_id and owner.turn_flags.get(PENDING_ACTIVATION) == activation_id)
    if consume and owner.turn_flags.get(USED) and not continuation:
        return None
    if continuation:
        # This subject is already the recipient this activation chose: the printed benefit applies once per
        # activation, never per target, pulse or repeated tick.
        return 0 if subject.current_hp >= subject.maximum_hp else _amount(engine, owner, subject)
    chosen = _select(engine, owner, subject, tuple(eligible_recipients), str(action_name), str(source)) if consume else None
    if consume and chosen is None:
        return None
    if not consume:
        # A pure estimate quotes the same number and spends nothing, choosing nothing and asking nothing.
        return 0 if subject.current_hp >= subject.maximum_hp else _amount(engine, owner, subject)
    owner.turn_flags[USED] = 1
    owner.turn_flags[CHOSEN] = chosen.entity_id
    amount = _amount(engine, owner, chosen)
    # The printed fallback tests maximum Hit Points *after* that healing, so the receipt is recorded on every
    # qualifying activation and the HEALING_APPLIED reader below decides against the landed result. A
    # recipient already at maximum gains no extra healing ("instead"), only the Temporary Hit Points.
    owner.turn_flags[PENDING] = _pb(engine, owner)
    owner.turn_flags[PENDING_ACTIVATION] = str(activation_id)
    owner.turn_flags[PENDING_SOURCE] = str(source)
    # ``stored_healing_reductions`` is called once for each subject in a
    # multi-target effect. The choice is activation-wide, but this offer belongs
    # only to the currently processed subject; returning the chosen amount for
    # the first subject would silently hand it to the wrong recipient.
    if chosen.entity_id != subject.entity_id:
        return 0
    return 0 if chosen.current_hp >= chosen.maximum_hp else amount


def _pb(engine: Any, owner: Any) -> int:
    row = row_of(engine, owner.entity_id, BLOCK, 'healing_bonus')
    return max(0, int(row['pb'])) if row is not None else 0


def _amount(engine: Any, owner: Any, subject: Any) -> int:
    """The printed healing increase: the Proficiency Bonus, doubled at CL12 on a 0 HP target."""
    pb = _pb(engine, owner)
    if pb <= 0:
        return 0
    cl = known_level(engine, owner)
    if cl is not None and cl >= 12 and subject.current_hp <= 0:
        return 2 * pb
    return pb


@hook('event')
def full_health_fallback(engine, event_type, kwargs):
    """A chosen recipient at maximum Hit Points *after* the qualifying heal gains Temporary HP instead.

    The printed text tests maximum Hit Points after that healing, so this reads the landed result rather
    than the pre-healing state: a recipient that reached full health from this heal gains the Temporary Hit
    Points the fallback promises, and a recipient still wounded below full gains none.
    """
    if event_type != 'HEALING_APPLIED':
        return
    payload = (kwargs or {}).get('payload') or {}
    # Only the current actor can hold the printed once-per-turn allowance, so a stale flag on some other
    # creature never spends this Insight's Temporary HP.
    actor = engine.state.actors.get(engine.state.current_actor_id)
    if actor is None or actor.turn_flags.get(CHOSEN) is None:
        return
    pending = int(actor.turn_flags.get(PENDING) or 0)
    if pending <= 0:
        return  # the chosen recipient gained ordinary healing instead of the fallback
    if (kwargs or {}).get('actor_id') != actor.entity_id:
        return  # only the owner's own qualifying heal resolves this receipt
    if str((kwargs or {}).get('source_definition_id') or '') != actor.turn_flags.get(PENDING_SOURCE):
        return
    if str(getattr(engine, '_healing_activation_id', '') or '') != actor.turn_flags.get(PENDING_ACTIVATION):
        return
    for entity_id in ((kwargs or {}).get('target_ids') or ()):
        subject = engine.state.actors.get(entity_id)
        if subject is None or subject.entity_id != actor.turn_flags.get(CHOSEN):
            continue
        if int(payload.get('after', 0)) < subject.maximum_hp:
            actor.turn_flags.pop(PENDING, None)  # still wounded below full: the increase already applied
            actor.turn_flags.pop(PENDING_ACTIVATION, None)
            actor.turn_flags.pop(PENDING_SOURCE, None)
            return
        actor.turn_flags.pop(PENDING, None)
        actor.turn_flags.pop(PENDING_ACTIVATION, None)
        actor.turn_flags.pop(PENDING_SOURCE, None)
        engine._grant_temp_hp(subject, pending, FEATURE, actor.entity_id)
        from .placed import note
        note(engine, FEATURE, actor, f'Restorative Circulation: {subject.display_name} is at full health after your '
             f'Qi-powered healing, so they gain {pending} Temporary Hit Points instead.', [subject])
        return


# ------------------------------------------------------------------------------------ Shared Breath Method
SB_FEATURE = 'insight.shared-breath-method'
SB_BLOCK = 'shared_breath_method'

SB_OUTCOME = ('Whenever you grant Temporary Cultivation Points to a willing creature with Feed Current, that '
              'creature also gains Temporary Hit Points equal to your Proficiency Bonus')


@hook('compile_block')
def compile_shared_breath(block, spec, row, numbers):
    if block != SB_BLOCK:
        return None
    return [{**row, 'kind': 'temporary_cp_rider', 'pb': int(numbers['pb']), 'player_outcome': SB_OUTCOME}]


@hook('temporary_cp_granted')
def feed_current_rider(engine, recipient, owner, amount, source):
    """Shared Breath Method's printed rider, on Feed Current's real grant and no other Temporary CP grant.

    The printed rule is "when you grant Temporary CP to a willing creature with
    Feed Current". The general ``temporary_cp_granted`` seam reports the granting
    source, so this rider attaches only to a Feed Current grant: another plug-in
    using the same documented seam grants Temporary CP of its own, and a later
    Feed Current grant is unaffected by this filter. Feed Current has already
    established that the recipient is a willing bonded creature and has recorded
    the spend, so this attaches to the actual grant and never to a preview or a
    refused payment.
    """
    from . import qiweaving_bond
    if not qiweaving_bond.is_feed_current_source(source):
        return
    row = row_of(engine, owner.entity_id, SB_BLOCK, 'temporary_cp_rider')
    if row is None:
        return
    pb = int(row['pb'])
    if pb <= 0:
        return
    engine._grant_temp_hp(recipient, pb, SB_FEATURE, owner.entity_id)
    from .placed import note
    note(engine, SB_FEATURE, owner, f'Shared Breath Method: {recipient.display_name} also gains {pb} Temporary '
         f'Hit Points from the Temporary Cultivation Points you granted.', [recipient])
