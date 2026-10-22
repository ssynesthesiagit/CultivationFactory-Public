"""Native outside-combat damage settlement shared by journey procedures.

Consumers: Dream Refinement's Harvest (dream_qi_scene) and any future journey
ability that damages a creature. One packet applies the creature's native
defenses exactly as combat does -- ActorTemplate resistances plus the persisted
condition ``rule`` rows read by standard_conditions -- then Temporary HP, HP,
the standard DAMAGE_COMMITTED receipt and the DYING state journey resume reads.
Absent defenses or snapshots mean ordinary damage; nothing is inferred from a
name, narration or damage source.
"""
import json

from ..journey import require


def _kinds(values):
    return {str(value).upper() for value in values or () if str(value)}


def defenses(actor, damage_type):
    """Native resistance/immunity kinds for one actor and damage type.

    ActorTemplate.damage_resistances is the compiled, saved standing defense.
    Persisted encounter conditions carry the same ``data.rule`` rows that
    combat/ext/standard_conditions reads; immunities use the parallel key.
    """
    kinds = _kinds((actor.get('bundle') or {}).get('actor_template', {}).get('damage_resistances'))
    immune = set()
    snapshot = actor.get('encounter_snapshot') or {}
    for raw in snapshot.get('conditions', {}).values():
        rule = (json.loads(raw).get('data') or {}).get('rule') or {}
        kinds |= _kinds(rule.get('damage_resistances'))
        immune |= _kinds(rule.get('damage_immunities'))
    return kinds, immune, str(damage_type).upper()


def snapshot(actor):
    """The journey encounter-health record, created from the saved template.

    Consumers: journey damage settlement and journey resume. This is the same
    integer/string shape journey_setup.encounter_snapshot writes, so a damage
    packet on a fresh journey survives a table commit and cold reload.
    """
    if actor.get('encounter_snapshot') is None:
        raw = actor['bundle']['actor_template']
        hp = int(raw.get('maximum_hp', raw.get('current_hp', 1)))
        actor['encounter_snapshot'] = {'current_hp': hp, 'maximum_hp': hp, 'temporary_hp': 0,
                                       'active': 1, 'life_state': '', 'conditions': {},
                                       'death_saves': {'ok': 0, 'bad': 0}}
    return actor['encounter_snapshot']


def settle(session, actor_id, amount, damage_type, source_definition_id, source_actor_id=None):
    """Apply one native damage packet to a journey creature; return HP lost.

    Defenses apply once (immunity zeroes, resistance halves once), then the
    packet is buffered by Temporary HP and committed as the engine's ordinary
    DAMAGE_COMMITTED receipt: ``rolled_or_pending_damage`` is the incoming
    amount, ``reduced_to`` the defended amount and ``hp_damage`` the HP lost.
    A creature dropped to zero keeps the journey DYING state and incapacitation
    that resume already understands. Providers and callers must not duplicate
    this arithmetic.
    """
    require(type(amount) is int and amount >= 0, 'Damage must be a nonnegative whole number.')
    require(type(damage_type) is str and bool(damage_type.strip()), 'Damage needs a real printed type.')
    require(type(source_definition_id) is str and bool(source_definition_id),
            'Damage needs its owning source record.')
    actor = session.state['actors'][actor_id]
    resist, immune, kind = defenses(actor, damage_type)
    defended = 0 if kind in immune or 'ALL' in immune else amount // 2 if kind in resist or 'ALL' in resist else amount
    snap = snapshot(actor)
    absorbed = min(defended, snap['temporary_hp'])
    snap['temporary_hp'] -= absorbed
    hp_before = snap['current_hp']
    hp_damage = defended - absorbed
    snap['current_hp'] = max(0, hp_before - hp_damage)
    session.emit('DAMAGE_COMMITTED', actor_id, source_definition_id=source_definition_id,
                 source_actor_id=source_actor_id, damage_type=str(damage_type).upper(),
                 rolled_or_pending_damage=amount, reduced_to=defended,
                 temporary_hp_absorbed=absorbed, hp_damage=hp_damage, hp_before=hp_before,
                 remaining_hp=snap['current_hp'], text=f'{actor["name"]} takes {hp_damage} {str(damage_type).title()} damage.')
    if snap['current_hp'] == 0:
        snap['life_state'] = 'DYING'
        actor['incapacitated'] = 1
    return hp_damage
