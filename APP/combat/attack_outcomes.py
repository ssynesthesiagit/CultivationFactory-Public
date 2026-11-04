"""Explicit per-attack outcomes shared by native/typed and portable attacks."""


def correct_ac_defense(total, armor_class, natural, spec, correction):
    """Resume a defense pipeline only after an explicit AC miss is corrected.

    Shared by typed self/ally defenses. The optional native callback owns the
    one-attempt limit, consent, payment and bonus damage for this attack.
    """
    if correction is None:
        return total, False
    changed = correction(total, armor_class)
    from .critical_attacks import hits
    return changed, changed != total and hits(natural, changed, armor_class, spec.get('critical_threshold', 20))


def hit_defense_reply(answer):
    """Normalize hit_response replies without guessing why a defense missed.

    Legacy (AC, hit) replies are terminal, and the number they carry is the AC that
    attack really had to beat, so it is published as that attempt's outcome receipt
    (``record_attack_outcome``). A mapping may explicitly identify an armor_class
    miss, or carry a forced outcome and its replaced natural die. A forced outcome is
    not a comparison against any AC at all -- an attack that strikes an afterimage, or
    an attacker's own action that simply fails -- so it declares no armor_class
    (``None``, or the key left out) and the fight then keeps the AC the roll was made
    against. That is the whole point of saying so: nothing is read as a higher AC, so
    no outcome receipt is published and no reader can mistake a forced miss for a roll
    that a number beat. This result is transient; providers record any paid natural
    change as usual.
    """
    if not isinstance(answer, dict):
        ac, hit = answer
        return ac, hit, 'terminal', None
    ac, hit = answer.get('armor_class'), answer.get('hit')
    reason, natural = answer.get('miss_reason'), answer.get('natural_result')
    if (reason not in ('armor_class', 'forced', 'natural_replaced') or type(hit) is not bool
            or natural is not None and (type(natural) is not int or not 1 <= natural <= 20)):
        raise ValueError('invalid hit-defense outcome')
    if reason == 'armor_class':
        if type(ac) is not int:
            raise ValueError('an armor_class miss names the AC the attack had to beat')
    else:
        ac = None            # a forced outcome, or a replaced natural, is never an AC deficit
        if hit:
            raise ValueError('a forced outcome cannot leave the attack landing')
    return ac, hit, reason, natural


def unconditional_miss():
    """The ``hit_response`` reply for an attack that fails whatever it rolled, for a plug-in that made it fail.

    Used by the abilities whose own text makes a hit miss without any AC being compared: an afterimage struck
    (combat/ext/monkey.py, combat/ext/unwritten_footprint.py), a guard's body in the way
    (combat/ext/shadow.py, combat/ext/soulstring_dancer.py), an attacker's action that fails or is slipped out of
    (combat/ext/near_and_far.py, combat/ext/last_inch_palm.py, combat/ext/white_heron.py, combat/ext/protection.py),
    a projectile turned or an array gate passed (combat/ext/air_currents.py, combat/ext/formation_riders.py) and a
    punchline that ends the scene (combat/ext/jester_riders.py). Returning one of these instead of a made-up AC
    keeps the printed rule honest: the fight keeps the AC the roll was made against, so nothing publishes an outcome
    receipt for this attack and no ability can read the miss as one the roll lost to a number.
    Numerical defenses instead return their real comparison threshold: Tusks uses
    the replacement target's AC; One-Legged Guard's attack penalty is equivalent
    to adding that penalty to the protected target's AC for this attack only.
    """
    return {'armor_class': None, 'hit': False, 'miss_reason': 'forced'}


# ------------------------------------------------------------------- the outcome one attempt really got
# Used by APP/combat/typed_reactions.py, which publishes it once for every way a defence can raise the AC a roll had to
# beat, and read by any ability that must know what this one attack really faced. Laughing Theft of Timing
# (APP/combat/ext/monkey.py) is the first: its printed "if the triggering roll fails because of this penalty" asks whether
# the fighter's own 1d6 is what made an attack miss, and the answer needs the AC the attack ended up facing -- which may
# be raised by a typed reaction row, by an armor_class modifier, or by a plug-in's own hit_response (Perfect Breath,
# Brace the Line, the Nine Star guard). Those three answer in shapes no single event covered, so they are read here, from
# one receipt, instead of each reader guessing from events that may or may not exist. A defence that made the attack miss
# without comparing any AC (``hit_defense_reply``'s forced outcome) publishes nothing at all, because there is no higher
# AC to report.
#
# This is bookkeeping for the attempt being resolved, never a fight event and never saved: it is keyed by the creature who
# rolled and by how many events the fight had recorded when the defence answered, and it is only ever readable inside the
# attempt that own roll opened, so it can never answer for the next swing or for a different creature, and it adds nothing
# at all to a recorded fight.


def attempt_end(engine, actor_id, after_index):
    """Where the attempt that opened at ``after_index`` ends: the index of ``actor_id``'s own next ATTACK_ROLLED, or the
    fight's present length when it has not swung since. One interval, one meaning, for every reader of that attempt's
    events or receipt -- the attempt is its roll and everything that answered it, and the next roll is a new attempt."""
    for position in range(int(after_index) + 1, len(engine.events)):
        event = engine.events[position]
        if event.event_type == "ATTACK_ROLLED" and event.actor_id == actor_id:
            return position
    return len(engine.events)


def record_attack_outcome(engine, attacker, armor_class, source_id=""):
    """Remember that a defence raised the AC one attack attempt really had to beat.

    ``attacker`` is the creature who rolled, ``armor_class`` the AC its roll was measured against once every defence had
    answered, and ``source_id`` the defence that raised it, for a reader's own log line. Only a real AC belongs here: an
    attack that was made to miss without a comparison (``unconditional_miss``) publishes nothing, because no reader may
    read its miss as one this roll lost to a number. Callers only publish a value they have already decided on; this
    records, it never changes the fight.
    """
    engine._typed_attack_outcome = {"actor_id": attacker.entity_id, "recorded": len(engine.events),
                                    "armor_class": int(armor_class), "source_id": str(source_id or "")}


def attack_outcome(engine, actor_id, after_index=-1):
    """The outcome receipt for the attempt ``actor_id`` is resolving, or None when it has none.

    ``after_index`` is that attempt's own ATTACK_ROLLED event index. The receipt must have been published inside the
    attempt that roll opened (``attempt_end``), so a roll whose AC no defence raised reads None instead of an earlier
    attempt's outcome, and a second swing of the same creature can never be settled with the first swing's receipt. Both
    bounds live here rather than in each reader, so every consumer of this contract gets them for free.
    """
    receipt = getattr(engine, "_typed_attack_outcome", None)
    if not isinstance(receipt, dict) or receipt.get("actor_id") != actor_id:
        return None
    recorded = int(receipt.get("recorded") or 0)
    if recorded <= int(after_index) or recorded > attempt_end(engine, actor_id, after_index):
        return None
    return receipt


def correct_miss(engine, actor, target, spec, roll, intent, total, armor_class):
    """Strict post-roll bonuses; the native caller retains hit checks and damage.

    Used by native and typed attacks. No subscriber means no event or mutation.
    Replies affect this attempt only; payment/choice exceptions unwind the action.
    """
    from . import ext
    from .critical_attacks import hits

    damage = 0
    for provider in ext.callbacks('attack_miss_correction'):
        reply = provider(engine, actor, target, spec, roll, intent, total, armor_class)
        if reply is None:
            continue
        if (not isinstance(reply, dict) or type(reply.get('bonus')) is not int
                or reply['bonus'] <= 0 or type(reply.get('bonus_damage', 0)) is not int
                or reply.get('bonus_damage', 0) < 0
                or not isinstance(reply.get('source_id'), str) or not reply['source_id']
                or not isinstance(reply.get('label'), str) or not reply['label'].strip()):
            raise ValueError('attack correction requires source_id, label and positive integer bonus')
        previous = total
        total += reply['bonus']
        hit = hits(roll.natural_result or 0, total, armor_class, spec.get('critical_threshold', 20))
        engine._append_event('PASSIVE_TRIGGERED', reply['source_id'], actor_id=actor.entity_id,
            target_ids=(target.entity_id,), payload={'attack_correction': True, 'roll_id': roll.roll_id,
            'attack_source_id': engine.d20_context(roll).get('source_id'),
            'previous_total': previous, 'modified_total': total, 'target_ac': armor_class,
            'hit_after_correction': hit,
            'log': f"{reply['label']}: {actor.display_name}'s {spec['attack_name']} against "
                   f"{target.display_name} gains +{reply['bonus']} to this attack roll ({total} against AC {armor_class})."})
        if hit:
            damage = reply.get('bonus_damage', 0)
            break
    return total, damage


def replace_miss_with_hit(engine, actor, target, spec, roll, intent, total, armor_class):
    """Apply explicit opt-in miss-to-hit outcome replacements.

    Unlike ``attack_miss_correction``, this seam replaces the attack outcome and
    does not add a roll bonus. Providers own any printed margin, consent and cost.
    It is queried for every ordinary rolled miss, including natural 1, but never
    after an attack has already been forced to miss. No provider means inert.
    """
    from . import ext
    for provider in ext.callbacks('attack_miss_outcome'):
        reply = provider(engine, actor, target, spec, roll, intent, total, armor_class)
        if reply is None:
            continue
        if (not isinstance(reply, dict) or reply.get('force_hit') is not True
                or not isinstance(reply.get('source_id'), str) or not reply['source_id']
                or not isinstance(reply.get('label'), str) or not reply['label'].strip()):
            raise ValueError('attack miss outcome requires force_hit, source_id and readable label')
        engine._append_event('PASSIVE_TRIGGERED', reply['source_id'], actor_id=actor.entity_id,
            target_ids=(target.entity_id,), payload={'attack_outcome_replaced': 'miss_to_hit',
            'attack_source_id': spec.get('source_definition_id'),
            'roll_id': roll.roll_id, 'natural_result': roll.natural_result,
            'previous_total': total, 'target_ac': armor_class,
            'log': f"{reply['label']}: {actor.display_name}'s {spec['attack_name']} against "
                   f"{target.display_name} hits despite the rolled miss."})
        return True
    return False


def discard_attempt_modes(engine, actor, modifier_ids):
    """Remove only modes created for a cancelled attempt, preserving held benefits."""
    for mid in modifier_ids:
        modifier = actor.modifiers.pop(mid, None)
        if modifier is not None:
            engine._append_event('MODIFIER_REMOVED', modifier.source_definition_id, actor_id=actor.entity_id,
                                 payload={'modifier_id': mid, 'reason': 'CANCELLED_ATTACK'})


def forced_miss(engine, actor, target, source_id, attack_index, roll, replies):
    """Apply only the replies to this attack's before_attack checkpoint.

    No actor flags or AC modifiers survive into another attack. The original die
    record remains intact; the separate receipt explains why even a 20 misses.
    """
    forced = False
    for reply in replies:
        if not isinstance(reply, dict) or 'force_miss' not in reply:
            continue
        if type(reply['force_miss']) is not bool:
            raise ValueError('force_miss must be a boolean')
        if not reply['force_miss']:
            continue
        cause, label = reply.get('source_id'), reply.get('label')
        if not isinstance(cause, str) or not cause or not isinstance(label, str) or not label.strip():
            raise ValueError('a forced miss requires a source_id and readable label')
        engine._append_event('ATTACK_FORCED_MISS', cause, actor_id=actor.entity_id, target_ids=(target.entity_id,),
            payload={'attack_source_id': source_id, 'attack_index': attack_index, 'roll_id': roll.roll_id,
                     'natural_result': roll.natural_result,
                     'log': f'{label}: {actor.display_name}\'s attack against {target.display_name} misses.'})
        forced = True
    return forced
