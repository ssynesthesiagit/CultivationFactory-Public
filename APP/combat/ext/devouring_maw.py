"""Heaven-Devouring Maw Body (rider lane C7, 2026-09-30: "i want everything we can automated").

Devoured Essence here records one damage type per Essence (printed record: "Each Essence records one valid damage type";
maximum Proficiency Bonus, +3 during Devour Heaven and Earth; valid: Acid, Cold, Fire, Force, Lightning, Necrotic, Poison,
Psychic, Radiant, Thunder). The pool is the shared named resource ``resource:named.devoured_essence``; the types sit beside it
in ``condition:typed.devoured_types`` (source-qualified records plus their type projection). Owned rows: ``path_passive`` kind ``devouring_maw``
with ``role`` swallow / feast / regurgitate / technique / devour.

Swallow Hostile Power  its Reaction row answers a hostile packet containing at least one valid stored type (row_allowed); the
                       owner asks which one valid type of the whole simultaneous instance to reduce (a mixed packet can
                       choose a later portion), and only that type's portion is reduced by 2d8 + CON (4d10 + CON during
                       Devour Heaven and Earth: reaction_amount). Its surplus never spills into another type. If at least
                       1 point of that portion is prevented, 1 Essence of the chosen type after it resolves (one normal gain
                       a round, up to the maximum). Maw Strike: once per turn after an unarmed hit, spend 1 Essence (asked;
                       its type) for +2d8/3d8/4d8 (by CL; 6d8 during Devour) of that type.
Feast upon Protection  once per turn after an unarmed hit, spend 3 Essence (asked): Constitution save; failure: one temporary
                       protection of the target (Temporary HP, a temporary AC bonus, one Resistance of a multi-resistance
                       condition, or damage reduction from a lasting effect of source CL at most 2 above yours) is set aside
                       until the start of your next turn, and +4d8 of a spent type; success: +2d8. Selecting one Resistance
                       leaves the condition's other Resistances, benefits and original duration in place.
Regurgitate Calamity   ``maw_regurgitate`` {"mode": "creature" | "line"}: 1 to 3 Essence of one type (asked); a ranged
                       Cultivation Attack for 3d8 per Essence, or a Dexterity save for 2d8 per Essence (half on a success).
Swallow the Technique  its Reaction row answers valid-type damage that is not a melee attack; 4d10 + CON; if it prevented all of
                       the valid portions, 2 Essence assigned among their actual types after the resolved instance.
                       A typed hostile row that declares ``unconsumable: true`` is explicitly immune to consumption and
                       is not offered to either Swallow reaction (the printed bar on both rows); the same bar is read
                       from the native ``unconsumable`` source flag.
Devour Heaven and Earth  named state "devour_heaven_and_earth": the numbers above, supernatural Bludgeoning/Piercing/Slashing
                       become valid, once per round 1 Essence when a hostile creature within 60 feet spends CP (the type its
                       activation dealt, else Force), and the World-Eating Bite (once per turn after an unarmed hit, 5 Essence,
                       asked: +10d8 of a consumed type, Constitution save; failure ends one temporary lasting effect helping the
                       target, or strips its Temporary HP and bars new Temporary HP when no legal effect exists. A successful
                       save ends nothing and bars new Temporary HP until the start of the user's next turn).
"""

from __future__ import annotations

from typing import Any

from . import effect, hook, note

PREFIX = "tianxia.subpath.body.heaven_devouring_maw_body.feature."
ESSENCE = "resource:named.devoured_essence"
TYPES_RECORD = "condition:typed.devoured_types"
SET_ASIDE = "condition:typed.feast_set_aside"
DOWNGRADED = "condition:typed.maw_immunity_as_resistance"
CAMPAIGN_POLICY = 'condition:typed.maw_after_death_policy'
FARMING_EXCLUSION = 'condition:typed.maw_farming_exclusion'
VALID = ("ACID", "COLD", "FIRE", "FORCE", "LIGHTNING", "NECROTIC", "POISON", "PSYCHIC", "RADIANT", "THUNDER")
PHYSICAL = ("BLUDGEONING", "PIERCING", "SLASHING")
DEVOUR = "devour_heaven_and_earth"

# Shared classification of temporary protections a source-backed effect supplies.
# Condition effect kinds that protect the holder (producer: states.state).
PROTECTION_CONDITION_KINDS = frozenset({"ward", "barrier", "damage_reduction"})
# Temporary lasting effects Bite may also end (not protections, but still source-backed defenses).
ENDABLE_CONDITION_KINDS = PROTECTION_CONDITION_KINDS | frozenset({"transformation", "aura", "stance"})
# Modifier fields that are temporary AC/resistance protections.
PROTECTION_MODIFIER_FIELDS = frozenset({"armor_class", "armor_class_vs_melee", "armor_class_vs_ranged",
                                        "damage_resistance", "damage_reduction"})
FAMILY = PREFIX.removesuffix('.feature.')
LEVELS = {'swallow': 3, 'regurgitate': 6, 'technique': 10, 'feast': 14, 'devour': 18}


def compile_profile(info: dict[str, Any]) -> dict[str, int] | None:
    """Native acquisition's source profile; this metadata grants no tier."""
    from pathlib import Path
    from ..subpath_acquisition import acquired_features
    selected = acquired_features(info.get('owner_sheet') or {}, Path(__file__).resolve().parents[2], include_unavailable=True)
    row = selected.get(PREFIX + 'swallow_hostile_power')
    if row is not None:
        if row['cl'] <= 0:
            return None
        cl = row['cl']
    elif any(str(k).startswith(PREFIX) for k in info['owned_ids']):
        cl = int(info['numbers']['cl'])
    else:
        return None
    pb = int(info['numbers'].get('pb') or info.get('pb') or 2)
    if cl != int(info['numbers']['cl']):
        pb = min(pb, 2 + (max(1, cl) - 1) // 4)
    document = info.get('owner_sheet') or {}
    con = next((a for a in (document.get('ability_scores_and_statistics') or {}).get('abilities', [])
                if str(a.get('ability')).upper() == 'CON'), {})
    modifier = int(con['modifier']) if 'modifier' in con else (int(con.get('score') or 10) - 10) // 2
    same_key = str((document.get('identity') or {}).get('key_ability') or 'CON').upper() == 'CON'
    same_level = cl == int(info['numbers']['cl'])
    dc = int(info['numbers'].get('save_dc') or 8 + pb + modifier) if same_key and same_level else 8 + pb + modifier
    attack = int(info['numbers'].get('attack_bonus') or pb + modifier) if same_key and same_level else pb + modifier
    return {'cl': cl, 'pb': pb, 'save_dc': dc, 'attack_bonus': attack, 'key_mod': modifier}


@hook('compile_passives')
def family_ownership(passives: list[dict[str, Any]], info: dict[str, Any]) -> list[dict[str, Any]]:
    profile = compile_profile(info)
    return [*passives, {'block': 'maw_family', 'feature_id': FAMILY, **profile}] if profile is not None else passives


@hook('compile_resources')
def family_pool(info: dict[str, Any]) -> list[Any] | None:
    profile = compile_profile(info)
    if profile is None:
        return None
    from ..gate2_runtime_models import ResourceDefinition
    return [ResourceDefinition(resource_id=ESSENCE, initial=0, maximum=profile['pb'])]


class EssenceSelection(list):
    """Transient payment selection; record indices never enter saved state."""
    def __init__(self, kinds, indices):
        super().__init__(kinds)
        self.indices = tuple(indices)


@hook('compile_actions')
def expel_action(info: dict[str, Any]) -> list[Any] | None:
    profile = compile_profile(info)
    if profile is None:
        return None
    for row in info.get('passives') or []:
        if row.get('kind') == 'devouring_maw':
            row.update(profile)
    from ..gate2_runtime_models import ActionDefinition, EconomyKind
    return [ActionDefinition(source_definition_id=f"action:typed.{info['short']}.maw_expel",
        display_name='Undigested Calamity: Expel All Essence', owner_id=info['actor_id'],
        economy=EconomyKind.ACTION, resolution_kind='TYPED', target_kind='SELF',
        parameters={'typed': {'source': PREFIX + 'swallow_hostile_power', 'numbers': dict(info['numbers']),
            'effects': [{'type': 'maw_expel'}], 'duration': {'kind': 'instant'}, 'riders': []},
            'expected_damage': 0})]


def expel(engine: Any, actor: Any) -> None:
    """Resolve the family's indivisible, unpreventable direct-HP consequence.

    A dedicated HP-loss receipt deliberately offers no damage-benefit trigger.
    This public family procedure is shared by the Action and scene lifecycle
    caller; unconsciousness alone never calls it.
    """
    count = len(stored(actor))
    if family_profile(engine, actor) is None or not count:
        return
    from ..gate2_runtime_models import DiceSpec
    source = PREFIX + 'swallow_hostile_power'
    roll = engine.roller.roll(DiceSpec(count=count, sides=6), actor_id=actor.entity_id,
                              reason='DAMAGE:Undigested Calamity', critical=False)
    engine._record_roll(roll)
    amount = max(0, int(roll.total))
    before = actor.current_hp
    # This is explicitly direct Hit Point damage. Ordinary damage callbacks,
    # redirection, temporary HP, floors and resource conversions do not run.
    actor.current_hp = max(0, before - amount)
    spend(engine, actor, stored(actor), source)
    engine._append_event('UNAVOIDABLE_DAMAGE_COMMITTED', source, actor_id=actor.entity_id,
        target_ids=(actor.entity_id,), payload={'damage_type': 'FORCE', 'rolled_or_pending_damage': amount,
            'hp_before': before, 'remaining_hp': actor.current_hp, 'hp_damage': amount,
            'essence_count': count, 'temporary_hp_absorbed': 0,
            'log': f'Undigested Calamity: {actor.display_name} expels all {count} Essence and takes {amount} Force damage directly to Hit Points.'})
    if actor.current_hp == 0 and actor.active:
        engine._defeat(actor, source, initial_damage_excess=max(0, amount - before))
    elif actor.concentration is not None and amount:
        engine._concentration_check(actor, amount, source_actor_id=actor.entity_id, damage_source_id=source)
    engine._check_victory()


@effect('maw_expel')
def expel_effect(ctx: Any, row: dict[str, Any]) -> None:
    expel(ctx.engine, ctx.actor)


@hook('compile_action')
def maw_line_recipients(action: Any, info: dict[str, Any]) -> Any:
    """Seal the printed creature-wide line scope for previews and resolution."""
    from copy import deepcopy
    typed = (action.parameters or {}).get('typed') or {}
    if not str(typed.get('source') or '').startswith(PREFIX):
        return None
    parameters = deepcopy(action.parameters)
    profile = compile_profile(info)
    if profile is not None:
        parameters['typed']['numbers'] = {**(typed.get('numbers') or {}), **profile}
    role = next((role for role, feature in {'regurgitate': 'regurgitate_calamity', 'devour': DEVOUR}.items()
                 if typed.get('source') == PREFIX + feature), None)
    if role is not None:
        parameters['typed']['min_cl'] = LEVELS[role]
    if typed.get('source') == PREFIX + DEVOUR:
        parameters['typed']['effects'] = [{**e, 'type': 'maw_devour_state'}
            if e.get('type') == 'state' and e.get('name') == DEVOUR else e for e in typed.get('effects') or []]
    if typed.get('source') == PREFIX + 'regurgitate_calamity' and (typed.get('area') or {}).get('shape') == 'line':
        parameters['typed']['area']['explicit_harmful_recipients'] = 'every_creature'
    if typed.get('source') == PREFIX + 'regurgitate_calamity':
        parameters['typed']['supernatural'] = True
        parameters['typed'].pop('weapon', None)
    return action.model_copy(update={'parameters': parameters})


@hook('critical_cancel')
def projected_calamity_is_not_a_weapon_critical(engine: Any, attacker: Any, target: Any,
                                              spec: dict[str, Any], roll: Any, intent: Any) -> bool:
    """The printed projected technique does not gain critical-hit riders."""
    return ('regurgitate' in _roles(engine, attacker)
            and (spec.get('typed') or {}).get('source') == PREFIX + 'regurgitate_calamity')


@hook('state_event')
def devour_capacity(engine: Any, event: Any) -> None:
    """Capacity follows the owned form while expired overflow remains spendable."""
    if event.event_type not in ('CONDITION_APPLIED', 'CONDITION_REMOVED') or event.payload.get('condition_id') not in (
            'condition:typed.state.' + DEVOUR, 'condition:typed.cultivation_suppression'):
        return
    for aid in event.target_ids:
        actor = engine.state.actors.get(aid)
        if actor is not None and family_profile(engine, actor) is not None and ESSENCE in actor.resources:
            engine._set_resource_maximum(actor, ESSENCE, _maximum(engine, actor),
                                         PREFIX + DEVOUR, retain_excess=True)


def raw_roles(engine: Any, actor: Any) -> dict[str, dict[str, Any]]:
    return {str(row.get("role")): row for row in (getattr(engine, "typed_passive_rows", {}) or {}).get(actor.entity_id, [])
            if row.get("block") == "path_rider" and row.get("kind") == "devouring_maw"}


def family_profile(engine: Any, actor: Any) -> dict[str, Any] | None:
    """Public source ownership/profile for the journey continuation caller."""
    return next((r for r in (getattr(engine, 'typed_passive_rows', {}) or {}).get(actor.entity_id, [])
                 if r.get('block') == 'maw_family'), None) or next(iter(raw_roles(engine, actor).values()), None)


def effective_profile(engine: Any, actor: Any) -> dict[str, Any]:
    """Current Body profile; the stored form still retains its creation CL."""
    from .activation_requirements import effective_cl
    base = family_profile(engine, actor) or {}
    profile = {key: int(base[key]) for key in ('cl', 'pb', 'save_dc', 'attack_bonus', 'key_mod')
               if type(base.get(key)) is int}
    if not profile:
        return profile
    original = int(profile.get('cl') or 1)
    cl = effective_cl(actor, original)
    if cl < original:
        before = int(profile.get('pb') or 0)
        pb = min(before, 2 + (max(1, cl) - 1) // 4)
        profile.update(cl=cl, pb=pb)
        for key in ('save_dc', 'attack_bonus'):
            if key in profile:
                profile[key] -= before - pb
    return profile


def _roles(engine: Any, actor: Any) -> dict[str, dict[str, Any]]:
    from .activation_requirements import effective_cl
    profile = effective_profile(engine, actor)
    return {role: {**row, **{k: profile[k] for k in ('cl', 'pb', 'save_dc', 'key_mod') if k in profile}}
            for role, row in raw_roles(engine, actor).items()
            if effective_cl(actor, int(profile.get('cl') or row.get('cl') or 1)) >= LEVELS.get(role, 99)}


@hook('state_event')
def death_ends_maw(engine: Any, event: Any) -> None:
    """Printed lifecycle: death, a lingering soul, or complete Body Refining suppression ends the state.

    The metaphysical consequence (Undigested Calamity) resolves only where the table-owner campaign
    declaration permits effects after death; otherwise the records simply end.
    """
    from .life_state import DEAD, SOUL
    from .activation_requirements import BODY_SUPPRESSION
    if event.event_type != 'CONDITION_APPLIED' or event.payload.get('condition_id') not in (DEAD, SOUL, BODY_SUPPRESSION):
        return
    for aid in event.target_ids:
        actor = engine.state.actors.get(aid)
        if actor is None or family_profile(engine, actor) is None:
            continue
        if stored(actor):
            if any(c.condition_id == CAMPAIGN_POLICY for c in actor.conditions.values()):
                expel(engine, actor)
            else:
                spend(engine, actor, stored(actor), PREFIX + 'swallow_hostile_power')
        from .states import PREFIX as STATE
        engine._remove_condition(actor, STATE + DEVOUR, PREFIX + DEVOUR)


@hook('choice_reactors')
def maw_choice_owners(engine: Any) -> tuple[str, ...] | None:
    """Probe human Maw owners on AI turns; eligibility stays at each checkpoint."""
    owners = tuple(a.entity_id for a in engine.state.actors.values() if a.active and _roles(engine, a))
    return owners or None


def _devour(engine: Any, actor: Any) -> bool:
    from .states import active

    return 'devour' in _roles(engine, actor) and bool(active(engine, actor, DEVOUR))


def stored(actor: Any) -> list[str]:
    held = next((c for c in actor.conditions.values() if c.condition_id == TYPES_RECORD), None)
    types = list((held.data or {}).get("types") or []) if held is not None else []
    return types[: int(actor.resources.get(ESSENCE, 0) or 0)]


def records(actor: Any) -> list[dict[str, Any]]:
    """Source-qualified Essence records; public read API for sheet and replay consumers."""
    held = next((c for c in actor.conditions.values() if c.condition_id == TYPES_RECORD), None)
    return [dict(r) for r in ((held.data or {}).get("records") or [])] if held else []


def restore_records(engine: Any, actor: Any, entries: list[dict[str, Any]]) -> None:
    """Restore authenticated journey holdings; never generate a new Essence."""
    if family_profile(engine, actor) is None or ESSENCE not in actor.resources:
        raise ValueError('Only a Maw owner can continue Devoured Essence')
    for row in entries:
        if (set(row) != {'type', 'source', 'source_cl', 'round', 'expires'} or row['type'] not in (*VALID, *PHYSICAL)
                or not isinstance(row['source'], str) or not row['source'] or row['expires'] != 'SCENE_END'
                or type(row['source_cl']) is not int or row['source_cl'] < 0
                or type(row['round']) is not int or row['round'] < 0):
            raise ValueError('Invalid continued Devoured Essence record')
    if len(entries) != actor.resources[ESSENCE]:
        raise ValueError('Continued Essence count disagrees with native resource holdings')
    _write(engine, actor, [r['type'] for r in entries], PREFIX + 'swallow_hostile_power', entries=entries)


def _write(engine: Any, actor: Any, types: list[str], source: str, *, entries=None) -> None:
    if entries is None:
        available = records(actor)
        entries = []
        for kind in types:
            match = next((r for r in available if r["type"] == kind), None)
            if match is not None:
                available.remove(match)
                entries.append(match)
    held = next((c for c in actor.conditions.values() if c.condition_id == TYPES_RECORD), None)
    if held is not None:
        actor.conditions.pop(held.instance_id)
        engine._append_event("CONDITION_REMOVED", source, actor_id=actor.entity_id, target_ids=(actor.entity_id,),
                             payload={"condition_id": TYPES_RECORD, "instance_id": held.instance_id})
    engine._apply_condition(actor, TYPES_RECORD, PREFIX + 'swallow_hostile_power', actor.entity_id, expires_on="UNTIL_REMOVED",
                            data={"types": list(types), "records": entries,
                                  "label": "Devoured Essence: " + (", ".join(t.title() for t in types) or "none")})


def _maximum(engine: Any, actor: Any) -> int:
    profile = effective_profile(engine, actor)
    pb = int(profile.get('pb', actor.proficiency_bonus))
    return pb + (3 if _devour(engine, actor) else 0)


def gain(engine: Any, actor: Any, kind: str, source: str, *, normal: bool = True, count: int = 1,
         source_cl: int = 0, intent: Any = None) -> int:
    """Gain Essence of ``kind`` up to the Maw's maximum; a normal gain is once per round. Returns how many were stored."""
    from .life_state import is_dead, SOUL
    if is_dead(actor) or any(c.condition_id == SOUL for c in actor.conditions.values()):
        return 0  # resolution after death cannot recreate the ended Body state
    if ESSENCE not in actor.resources or not _roles(engine, actor) or kind.upper() not in (*VALID, *PHYSICAL):
        return 0
    if kind.upper() in PHYSICAL and not _devour(engine, actor):
        return 0
    if normal and actor.turn_flags.get("_round_essence_gain") == int(engine.state.round_number):
        return 0
    from . import run_strict
    allowed = run_strict('resource_gain_allowed', engine, actor, ESSENCE, count, source)
    if any(type(reply) is not bool for reply in allowed):
        raise ValueError('resource_gain_allowed requires a boolean')
    if False in allowed:
        return 0
    types = stored(actor)
    maximum = _maximum(engine, actor)
    if len(types) > maximum:
        return 0
    entries = records(actor)
    gained = 0
    from .needle import ask, checkpoint_id
    for index in range(max(0, count)):
        if len(types) == maximum:
            options = [str(i) for i in range(len(types))]
            picked = ask(engine, intent, checkpoint_id(engine, f"maw_replace_{index}", actor.entity_id), actor,
                         "choice:needle.maw_replace", options, allow_decline=True,
                         labels={str(i): f"Replace {t.title()} Essence (record {i + 1})" for i, t in enumerate(types)},
                         prompt=f"Devoured Essence: {actor.display_name} is full. Replace one record with {kind.title()} Essence, or decline?")
            if not picked:
                continue
            remove = int(picked[0])
            types.pop(remove)
            if remove < len(entries):
                entries.pop(remove)
        types.append(kind.upper())
        entries.append({"type": kind.upper(), "source": source, "source_cl": int(source_cl),
                        "round": int(engine.state.round_number), "expires": "SCENE_END"})
        gained += 1
    if not gained:
        return 0
    # The named pool's static maximum is PB; Devour's temporary maximum is
    # authoritative here, including retained overflow when that state ends.
    before = int(actor.resources.get(ESSENCE, 0))
    actor.resources[ESSENCE] = len(types)
    engine._append_event("RESOURCE_GAINED", source, actor_id=actor.entity_id,
                         payload={"resource_id": ESSENCE, "requested": gained, "gained": len(types) - before,
                                  "current": len(types)})
    _write(engine, actor, types, source, entries=entries)
    if normal and gained:
        actor.turn_flags["_round_essence_gain"] = int(engine.state.round_number)
    return gained


def spend(engine: Any, actor: Any, kinds: list[str], source: str) -> None:
    types = stored(actor)
    if isinstance(kinds, EssenceSelection):
        indices = set(kinds.indices)
        if len(indices) != len(kinds) or sorted(types[i] for i in indices) != sorted(kinds):
            raise ValueError('The selected Essence records are no longer available')
        entries = records(actor)
        remaining = [t for i, t in enumerate(types) if i not in indices]
        engine._spend_resource(actor, ESSENCE, len(kinds), source)
        _write(engine, actor, remaining, source, entries=[r for i, r in enumerate(entries) if i not in indices])
        return
    for kind in kinds:
        types.remove(kind)
    engine._spend_resource(actor, ESSENCE, len(kinds), source)
    _write(engine, actor, types, source)


def _valid(engine: Any, actor: Any, kind: str) -> bool:
    """A valid stored type; during Devour Heaven and Earth also Bludgeoning/Piercing/Slashing from a supernatural source (a
    technique, or a weapon that is not mundane) -- read from the packet now being dealt."""
    kind = str(kind or "").upper()
    if kind in VALID:
        return True
    if kind not in PHYSICAL or not _devour(engine, actor):
        return False
    from ..pending_damage import current
    pending = current(engine)
    if pending is not None and 'supernatural_attack' in pending.source_flags:
        return True
    packet = getattr(engine, "_typed_damage_packet", None) or {}
    action = engine.action_catalog.get(str(packet.get("source") or (pending.source_id if pending is not None else '') or ""))
    typed = ((action.parameters or {}).get("typed") or {}) if action is not None else {}
    return typed.get("supernatural") is True or typed.get('mundane') is False or bool(typed.get("sphere") and not typed.get("weapon"))


def farming_excluded(actor: Any, source_actor_id: str | None) -> bool:
    """A source-scoped native table-owner admission, not a team/name guess."""
    return any(c.condition_id == FARMING_EXCLUSION and c.data.get('source_actor_id') == source_actor_id
               for c in actor.conditions.values())


def _pick_type(engine: Any, actor: Any, intent: Any, prompt: str, count: int = 1, target_id: str | None = None) -> list[str] | None:
    """Ask which stored types to spend (``count`` Essence, any mix); None when the owner declines."""
    from .needle import ask, checkpoint_id

    types = stored(actor)
    if len(types) < count:
        return None
    options = sorted(set(types))
    if count == 1:
        picked = ask(engine, intent, checkpoint_id(engine, "maw_type", actor.entity_id), actor, "choice:needle.maw_type", options,
                     allow_decline=True, labels={o: f"Spend 1 {o.title()} Essence" for o in options}, prompt=prompt, target_id=target_id)
        return [picked[0]] if picked else None
    options = [str(i) for i in range(len(types))]
    picked = ask(engine, intent, checkpoint_id(engine, f"maw_types_{count}", actor.entity_id), actor, "choice:needle.maw_types",
                 options, minimum=count, maximum=count, allow_decline=True,
                 labels={str(i): f"{t.title()} Essence (record {i + 1})" for i, t in enumerate(types)},
                 prompt=prompt, target_id=target_id)
    if not picked:
        return None
    kinds = [types[int(i)] for i in picked]
    damage = ask(engine, intent, checkpoint_id(engine, f"maw_damage_type_{count}", actor.entity_id), actor,
                 "choice:needle.maw_damage_type", sorted(set(kinds)),
                 labels={k: f"Deal {k.title()} damage" for k in set(kinds)}, prompt=prompt + " Choose a consumed damage type.",
                 target_id=target_id)
    if damage:
        kinds.remove(damage[0])
        kinds.insert(0, damage[0])
    return EssenceSelection(kinds, [int(i) for i in picked])


# ------------------------------------------------------------------------------------------- Swallow Hostile Power
def _allocate_reduction(engine: Any, actor: Any, amount: int, remaining: int, kind: str) -> int:
    """Every integer allocation is reachable; AI prefers preventing this portion."""
    from .needle import ask, checkpoint_id
    maximum = min(max(0, amount), max(0, remaining))
    if maximum == 0:
        return 0
    picked = ask(engine, getattr(engine, '_active_intent', None),
        checkpoint_id(engine, 'maw_allocate', actor.entity_id), actor, 'choice:needle.maw_allocate',
        [str(n) for n in range(maximum, -1, -1)],
        labels={str(n): f'Prevent {n} {kind.title()} damage; retain {remaining - n} reduction for other valid portions'
                for n in range(maximum, -1, -1)},
        prompt=f'Swallow the Technique: allocate the remaining {remaining} reduction for '
               f'{actor.display_name}. This {kind.title()} portion would deal {amount} damage.',
        target_id=actor.entity_id)
    return int(picked[0]) if picked else 0


def _technique_response(engine: Any, target: Any, source_id: str, source_actor_id: str) -> dict[str, Any] | None:
    from ..save_context import damage_save, damage_response_state
    proposal = damage_save(engine, target.entity_id, source_id, source_actor_id)
    if proposal is not None:
        return damage_response_state(engine, proposal, PREFIX + 'swallow_the_technique')
    attack = engine.damage_context()
    if attack is not None:
        from .attack_reduction import key_for
        return engine.__dict__.setdefault('_maw_attack_responses', {}).setdefault(key_for(attack), {})
    return None


@hook('damage_instance_requested')
def swallow_instance_requested(engine: Any, ctx: Any, effects: list[dict[str, Any]]) -> bool | None:
    """Ask for the whole simultaneous instance only when a Swallow owner can answer it.

    The printed procedure chooses one valid type "in that packet": a Fire-then-Necrotic
    instance can be answered at its first portion. The executor's collection rolls every
    portion before the first commit, so no character without the ability may cause it.
    """
    if sum(1 for effect in effects if isinstance(effect, dict) and effect.get('type') == 'damage') < 2:
        return None
    recipients = [ctx.target] if getattr(ctx, 'target', None) is not None else list(getattr(ctx, 'targets', ()) or ())
    for recipient in recipients:
        if recipient is not None and recipient.active and 'swallow' in _roles(engine, recipient):
            return True
    return None


@hook('reaction_rows')
def maw_reduction_types(engine: Any, actor_id: str, block: str, rows: list[dict[str, Any]]) -> list[dict[str, Any]] | None:
    """Bind the reduction to the triggering portion until the owner chooses one valid type.

    ``only_damage_types`` is a committed-budget filter, not a menu: the multiple valid
    types of a whole instance become exactly one in ``devour_swallow`` after the owner
    answers the printed "choose one type" question.
    """
    from copy import deepcopy
    actor = engine.state.actors.get(actor_id)
    if actor is None:
        return None
    changed = False
    result = []
    for row in rows:
        feature = row.get('feature_id')
        if feature not in (PREFIX + 'swallow_hostile_power', PREFIX + 'swallow_the_technique'):
            result.append(row)
            continue
        copied = deepcopy(row)
        copied['damage_quote_after_consent'] = True
        selected = str(getattr(engine, '_typed_pending_damage_type', '') or '').upper()
        kinds = [selected] if feature.endswith('swallow_hostile_power') else [k for k in (*VALID, *PHYSICAL) if _valid(engine, actor, k)]
        for eff in copied.get('effects') or []:
            if eff.get('type') == 'damage_modifier':
                eff['only_damage_types'] = kinds
        result.append(copied)
        changed = True
    return result if changed else None


@hook("row_allowed")
def maw_reactions(engine: Any, actor: Any, row: dict[str, Any]) -> bool | None:
    feature = str(row.get("feature_id") or "")
    if feature not in (PREFIX + "swallow_hostile_power", PREFIX + "swallow_the_technique"):
        return None
    if ('technique' if feature.endswith('swallow_the_technique') else 'swallow') not in _roles(engine, actor):
        return False
    kind = str(getattr(engine, "_typed_pending_damage_type", None) or "").upper()
    packet = getattr(engine, "_typed_damage_packet", None) or {}
    from ..pending_damage import current
    pending = current(engine)
    source_actor = engine.state.actors.get(pending.source_actor_id) if pending else None
    if pending is None or farming_excluded(actor, pending.source_actor_id) or not pending.hostile or (source_actor is not None and source_actor.owner_id is not None) or pending.pressure_kind != 'damage' or pending.source_flags.intersection(
            {'willing_cost', 'unconsumable', 'maximum_hp_loss', 'anti_farming'}):
        return False
    # The trigger is a packet containing at least one valid stored type; the current
    # portion may be an invalid one (Slashing outside Devour) while a later portion
    # of the same simultaneous instance is valid.
    instance_types = [str(portion.get('type') or '').upper()
                      for portion in (getattr(engine, '_typed_damage_instance', None) or [])]
    if not any(_valid(engine, actor, option) for option in dict.fromkeys([kind, *instance_types]) if option):
        return False
    action = engine.action_catalog.get(pending.source_id)
    typed = (action.parameters.get('typed') or {}) if action is not None else {}
    if typed.get('unconsumable') is True:
        # The printed bar "damage explicitly immune to consumption" / "a technique
        # explicitly barring consumption": a typed source row declares it in its own data.
        return False
    if feature.endswith("swallow_the_technique"):
        if typed.get('permanent_artifact_effect') is True or 'permanent_artifact_effect' in pending.source_flags:
            return False
        from ..save_context import damage_save
        if not packet.get('ranged') and not typed.get('area') and damage_save(
                engine, actor.entity_id, pending.source_id, pending.source_actor_id) is None:
            return False
    return None


def _choose_swallow_type(engine: Any, actor: Any, pending: Any, valid_types: list[str], roll_total: int) -> str:
    """The printed "choose one type": asked once when the packet offers more than one valid type."""
    if len(valid_types) <= 1:
        return valid_types[0] if valid_types else ''
    from .needle import ask, checkpoint_id

    action = engine.action_catalog.get(pending.source_id)
    action_name = getattr(action, 'display_name', None) or 'the triggering damage'
    options = sorted(valid_types)
    picked = ask(engine, getattr(engine, '_active_intent', None),
                 checkpoint_id(engine, 'maw_swallow_type', actor.entity_id), actor,
                 'choice:needle.maw_swallow_type', options,
                 labels={kind: f'Reduce {kind.title()} damage by {roll_total}' for kind in options},
                 prompt=f'Swallow Hostile Power: {actor.display_name} can reduce one valid damage type of '
                        f'{action_name}. Choose the damage type to reduce.',
                 target_id=actor.entity_id)
    return picked[0] if picked else ''


@hook("reaction_amount")
def devour_swallow(engine: Any, actor: Any, row: dict[str, Any], eff: dict[str, Any]) -> int | None:
    feature = str(row.get("feature_id") or "")
    if feature not in (PREFIX + "swallow_hostile_power", PREFIX + "swallow_the_technique"):
        return None
    from ..gate2_runtime_models import DiceSpec

    upgraded = feature.endswith('swallow_the_technique') or _devour(engine, actor)
    modifier = int((row.get('ability_mods') or {}).get('CON', (row.get('numbers') or {}).get('con', 0)))
    roll = engine.roller.roll(DiceSpec(count=4 if upgraded else 2, sides=10 if upgraded else 8, modifier=modifier),
                              actor_id=actor.entity_id, reason=f"REACTION:{row.get('feature_id')}", critical=False)
    engine._record_roll(roll)
    if feature.endswith('swallow_hostile_power'):
        from ..pending_damage import packet_scratch, current
        pending = current(engine)
        scratch = packet_scratch(engine)
        if pending is not None and scratch is not None:
            instance = getattr(engine, '_typed_damage_instance', None) or []
            candidates = [str(pending.damage_type or '').upper(), *(portion['type'] for portion in instance)]
            valid_types = [kind for kind in dict.fromkeys(candidates) if kind and _valid(engine, actor, kind)]
            chosen = _choose_swallow_type(engine, actor, pending, valid_types, int(roll.total))
            if chosen:
                scratch['maw_swallow_kind'] = chosen
                # Only the chosen type's portion is reduced: the surplus may never
                # spill into another type (or an invalid physical portion).
                eff['only_damage_types'] = [chosen]
                # The reaction's own packet absorbs min(roll, its amount) when it is
                # the chosen type; otherwise nothing is applied here and the whole
                # roll is carried to the chosen type's own portion.
                absorbed = (min(int(roll.total), pending.amount)
                            if str(pending.damage_type or '').upper() == chosen else 0)
                scratch['maw_swallow_remaining'] = max(0, int(roll.total) - absorbed)
    if feature.endswith('swallow_the_technique'):
        from ..pending_damage import packet_scratch, current
        scratch = packet_scratch(engine)
        pending = current(engine)
        total = max(0, int(roll.total))
        allocated = _allocate_reduction(engine, actor, pending.amount, total, pending.damage_type) if pending else total
        if scratch is not None:
            scratch['maw_technique_remaining'] = total - allocated
        return allocated
    return int(roll.total)


@hook("state_event")
def essence_after_swallow(engine: Any, last: Any) -> None:
    event_type = last.event_type
    kwargs = {'payload': last.payload, 'actor_id': last.actor_id}
    if event_type == "REACTION_RESOLVED" and last is not None and last.source_definition_id in (PREFIX + "swallow_hostile_power", PREFIX + "swallow_the_technique"):
        payload = kwargs.get("payload") or {}
        before, after = int(payload.get("pending_before") or 0), int(payload.get("pending_after") or 0)
        pending_type = str(getattr(engine, "_typed_pending_damage_type", None) or "FORCE").upper()
        technique = last.source_definition_id.endswith("swallow_the_technique")
        from ..pending_damage import current, packet_scratch
        pending = current(engine)
        scratch = packet_scratch(engine) or {}
        # Swallow Hostile Power reduces the one chosen type. When that type is not the
        # portion being committed now, the budget is carried to its own portion and the
        # Essence is deferred from the carry callback instead (reaction_reduction_carried
        # for attacks, swallow_same_type_save_budget for saves).
        chosen = (str(scratch.get('maw_swallow_kind') or '') or pending_type).upper()
        kind = pending_type if technique else chosen
        if technique or before > after or (pending is not None and chosen != pending_type):
            action = engine.action_catalog.get(pending.source_id) if pending else None
            source_cl = (((action.parameters or {}).get('typed') or {}).get('numbers') or {}).get('cl', 0) if action else 0
            if technique and pending is not None:
                actor = engine.state.actors[pending.target_id]
                state = _technique_response(engine, actor, pending.source_id, pending.source_actor_id)
                if state is not None:
                    state['remaining'] = int(scratch.get('maw_technique_remaining', 0))
                engine.__dict__.setdefault('_maw_techniques', []).append({
                    'actor': pending.target_id, 'source': pending.source_id, 'source_actor': pending.source_actor_id,
                    'source_cl': source_cl, 'sequence': pending.event_sequence, 'types': [kind],
                    'valid_types': [k for k in (*VALID, *PHYSICAL) if _valid(engine, actor, k)]})
            elif pending is not None:
                from ..save_context import damage_save, damage_response_state
                proposal = damage_save(engine, pending.target_id, pending.source_id, pending.source_actor_id)
                if proposal is not None and engine.damage_context() is None:
                    state = damage_response_state(engine, proposal, PREFIX + 'swallow_hostile_power')
                    state.update(remaining=int(scratch.get('maw_swallow_remaining', 0)), kind=chosen)
                if before > after:
                    engine.__dict__.setdefault("_maw_pending", []).append((kwargs.get("actor_id"), chosen, 1,
                        True, pending.source_id, source_cl))
    elif event_type == "DAMAGE_COMMITTED":
        for entry in engine.__dict__.get('_maw_techniques', []):
            if (entry['actor'] in last.target_ids and entry['source'] == last.source_definition_id
                    and entry['source_actor'] == last.actor_id):
                actor = engine.state.actors[entry['actor']]
                kind = str(last.payload.get('damage_type') or '').upper()
                if _valid(engine, actor, kind) and kind not in entry['types']:
                    entry['types'].append(kind)
        waiting = engine.__dict__.get("_maw_pending") or []
        if not waiting:
            return
        waiting = [r for r in waiting if r[0] in last.target_ids and r[4] == last.source_definition_id]
        engine.__dict__["_maw_pending"] = [r for r in engine.__dict__["_maw_pending"] if r not in waiting]
        for actor_id, kind, count, normal, source, source_cl in waiting:
            actor = engine.state.actors.get(actor_id or "")
            if actor is not None and actor.active:
                gain(engine, actor, kind, source, normal=normal, count=count, source_cl=source_cl)


@hook('damage_pending')
def swallow_same_type_save_budget(engine: Any, target: Any, amount: int, source_id: str, source_actor_id: str) -> int | None:
    """One chosen type's surplus stays inside its native recipient/save only."""
    if 'swallow' not in _roles(engine, target) or engine.damage_context() is not None:
        return None
    from ..save_context import damage_save, damage_response_state
    proposal = damage_save(engine, target.entity_id, source_id, source_actor_id)
    if proposal is None:
        return None
    state = damage_response_state(engine, proposal, PREFIX + 'swallow_hostile_power')
    if state.get('kind') != str(getattr(engine, '_typed_pending_damage_type', '') or '').upper():
        return None
    reduction = min(amount, state.get('remaining', 0))
    state['remaining'] -= reduction
    if not reduction:
        return None
    # The reaction may have been declared on an earlier portion of this save; the
    # chosen type's own portion is reduced here, so its Essence is deferred until
    # this packet commits (the once-per-round gain limit still applies).
    action = engine.action_catalog.get(source_id)
    source_cl = (((action.parameters or {}).get('typed') or {}).get('numbers') or {}).get('cl', 0) if action else 0
    engine.__dict__.setdefault('_maw_pending', []).append(
        (target.entity_id, str(state.get('kind') or ''), 1, True, source_id, source_cl))
    return amount - reduction


@hook('reaction_reduction_carried')
def swallow_carried_essence(engine: Any, target: Any, feature: str, absorbed: int) -> None:
    """Swallow Hostile Power reduced a later portion of the instance: award after its commit.

    The chosen type's surplus is carried by the shared attack budget when the owner
    answered an earlier portion. ``absorbed`` is the amount this portion lost, so the
    printed "at least 1 point is reduced" condition is already proven.
    """
    if feature != PREFIX + 'swallow_hostile_power' or int(absorbed) <= 0 or 'swallow' not in _roles(engine, target):
        return
    kind = str(getattr(engine, '_typed_pending_damage_type', '') or '').upper()
    if not kind or not _valid(engine, target, kind):
        return
    from ..pending_damage import current
    pending = current(engine)
    source_id = pending.source_id if pending is not None else ''
    action = engine.action_catalog.get(source_id)
    source_cl = (((action.parameters or {}).get('typed') or {}).get('numbers') or {}).get('cl', 0) if action else 0
    engine.__dict__.setdefault('_maw_pending', []).append((target.entity_id, kind, 1, True, source_id, source_cl))


@hook('damage_pending')
def technique_save_budget(engine: Any, target: Any, amount: int, source_id: str, source_actor_id: str) -> int | None:
    """Reuse the native recipient/save-local state across split damage rows.

    A different save, source or target gets its own native response dictionary;
    no held resource or budget survives the resolved instance.
    """
    if 'technique' not in _roles(engine, target):
        return None
    state = _technique_response(engine, target, source_id, source_actor_id)
    remaining = state.get('remaining', 0) if state is not None else 0
    kind = str(getattr(engine, '_typed_pending_damage_type', '') or '').upper()
    if not remaining or not _valid(engine, target, kind):
        return None
    reduction = _allocate_reduction(engine, target, amount, remaining, kind)
    state['remaining'] -= reduction
    return amount - reduction


@hook('attack_damage_final')
def finish_technique_attack(engine: Any, attacker: Any, target: Any, provenance: Any, intent: Any) -> None:
    from .attack_reduction import key_for
    engine.__dict__.get('_maw_attack_responses', {}).pop(key_for(provenance), None)


@hook('activation_settlement')
def technique_essence_settlement(ctx: Any, receipt: dict[str, Any]) -> None:
    """Award only after every committed portion in the native activation.

    Damage-required consequences use the committed zero damage, while ordinary
    hit/save consequences remain untouched. Each record's type is a player
    decision from the actual valid types in the resolved instance.
    """
    engine = ctx.engine
    waiting = [e for e in engine.__dict__.get('_maw_techniques', [])
               if e['source'] == ctx.damage_source and e['source_actor'] == ctx.actor.entity_id
               and e['sequence'] >= receipt['first_sequence']]
    engine.__dict__['_maw_techniques'] = [e for e in engine.__dict__.get('_maw_techniques', []) if e not in waiting]
    from .needle import ask, checkpoint_id
    for entry in waiting:
        actor = engine.state.actors[entry['actor']]
        packets = [e for e in engine.events[receipt['first_sequence']:]
                   if e.event_type == 'DAMAGE_COMMITTED' and actor.entity_id in e.target_ids
                   and e.actor_id == entry['source_actor'] and e.source_definition_id == entry['source']
                   and str(e.payload.get('damage_type') or '').upper() in entry['valid_types']]
        if not packets or any(int(e.payload.get('reduced_to') or 0) > 0 for e in packets):
            continue
        entry['types'] = sorted({str(e.payload['damage_type']).upper() for e in packets})
        for i in range(2):
            picked = ask(engine, ctx.intent, checkpoint_id(engine, f'maw_technique_gain_{i}', actor.entity_id),
                actor, 'choice:needle.maw_technique_gain', sorted(entry['types']),
                labels={k: f'Store 1 {k.title()} Essence' for k in entry['types']},
                prompt=f'Swallow the Technique: {actor.display_name} consumed the valid damage from '
                       f'{ctx.action.display_name}. Choose the type for Essence {i + 1} of 2.')
            if picked:
                gain(engine, actor, picked[0], entry['source'], normal=False, source_cl=entry['source_cl'], intent=ctx.intent)


@hook('effect_batch_resolved')
def technique_instance_settled(ctx: Any, first_event: int) -> None:
    """Persistent zones settle each native resolved outcome, never the zone."""
    if not ctx.engine.__dict__.get('_maw_techniques'):
        return
    technique_essence_settlement(ctx, {'first_sequence': first_event})


# ------------------------------------------------------------------------------------------ on-hit spends
def _stamp(engine: Any) -> str:
    current = engine.state.actors.get(engine.state.current_actor_id)
    return f"{engine.state.round_number}:{engine.state.current_actor_id}:{current.turns_started if current else 0}"


@hook("after_hit_choice")
def maw_hits(ctx: Any, target: Any, kind: str) -> None:
    engine, actor = ctx.engine, ctx.actor
    roles = _roles(engine, actor)
    if kind != "unarmed" or target is None or not target.active or not roles or not stored(actor):
        return
    from .. import typed_executor as te

    profile = effective_profile(engine, actor)
    own_typed = {**ctx.typed, 'numbers': {**ctx.numbers, **{k: profile[k] for k in ('cl', 'pb', 'save_dc', 'key_mod') if k in profile}}}
    sub = ctx.on_hit_context(target, action=ctx.action, typed=own_typed, damage_cache={})
    sub.damage_source_flags = (*sub.damage_source_flags, 'supernatural_attack')
    devour = _devour(engine, actor)
    if "devour" in roles and devour and actor.turn_flags.get("_round_world_bite") != _stamp(engine) and len(stored(actor)) >= 5:
        kinds = _pick_type(engine, actor, ctx.intent, f"World-Eating Bite: {ctx.action.display_name} hit {target.display_name}; spend 5 Essence "
                           "for +10d8 of a consumed type and a Constitution save to end one temporary defensive effect? "
                           "If no effect can end, remove its Temporary Hit Points and bar new ones. A successful save bars new Temporary Hit Points "
                           "until the start of your next turn.", count=5, target_id=target.entity_id)
        if kinds:
            actor.turn_flags["_round_world_bite"] = _stamp(engine)
            spend(engine, actor, kinds, PREFIX + "devour_heaven_and_earth")
            te.run_effects(sub, [{"type": "extra_damage", "applies_to": "target", "dice": {"count": 10, "sides": 8}, "damage_types": [kinds[0].lower()]},
                                 {"type": "save", "ability": "con", "on_fail": [{"type": "maw_break_defense"}],
                                  "on_success": [{"type": "deny_temp_hp", "applies_to": "target", "expires_on": "START_OF_SOURCE_NEXT_TURN"}]}])
    if "feast" in roles and target.active and actor.turn_flags.get("_round_feast") != _stamp(engine) and len(stored(actor)) >= 3:
        kinds = _pick_type(engine, actor, ctx.intent, f"Feast upon Protection: {ctx.action.display_name} hit {target.display_name}; spend 3 Devoured Essence? "
                           "A failed Constitution save suppresses one temporary protection until the start of your next turn and deals +4d8 "
                           "of a consumed type; a successful save deals +2d8 without suppressing a protection.",
                           count=3, target_id=target.entity_id)
        if kinds:
            actor.turn_flags["_round_feast"] = _stamp(engine)
            spend(engine, actor, kinds, PREFIX + "feast_upon_protection")
            dtype = kinds[0].lower()
            te.run_effects(sub, [{"type": "save", "ability": "con", "evidence": "Feast upon Protection: Constitution saving throw",
                                  "on_fail": [{"type": "maw_set_aside"}, {"type": "damage", "applies_to": "target", "dice": {"count": 4, "sides": 8}, "damage_types": [dtype]}],
                                  "on_success": [{"type": "damage", "applies_to": "target", "dice": {"count": 2, "sides": 8}, "damage_types": [dtype]}]}])
    if "swallow" in roles and target.active and actor.turn_flags.get("_round_maw_strike") != _stamp(engine) and stored(actor):
        cl = int(roles['swallow'].get('cl') or ctx.numbers.get("cl") or 1)
        count = 6 if devour else 4 if cl >= 17 else 3 if cl >= 11 else 2
        kinds = _pick_type(engine, actor, ctx.intent, f"Maw Strike: {ctx.action.display_name} hit {target.display_name}; spend 1 Devoured Essence "
                           f"for +{count}d8 damage of its stored type (once per turn)?",
                           target_id=target.entity_id)
        if kinds:
            actor.turn_flags["_round_maw_strike"] = _stamp(engine)
            spend(engine, actor, kinds, PREFIX + "swallow_hostile_power")
            te.run_effects(sub, [{"type": "extra_damage", "applies_to": "target", "dice": {"count": count, "sides": 8}, "damage_types": [kinds[0].lower()],
                                  "evidence": "Maw Strike"}])


def _protections(ctx: Any, target: Any) -> dict[str, tuple[str, str, str, str | None]]:
    """Selectable temporary protections: (kind, instance key, player label, resistance type or None).

    A condition that grants several Resistances is offered one type at a time: the
    printed clause suppresses "one Resistance", not the whole condition (and the
    other Resistances and benefits keep their original duration).
    """
    from . import end_effect
    from .source_eligibility import ends_by_itself

    out: dict[str, tuple[str, str, str, str | None]] = {}
    cl = int(ctx.numbers.get("cl") or 1)
    if int(target.temporary_hp or 0) > 0:
        from .temp_hp_grants import held_grant
        held = held_grant(ctx.engine.events, target.entity_id)
        grant = next((e for e in ctx.engine.events if held is not None and e.sequence == held[2]), None)
        action = ctx.engine.action_catalog.get(grant.source_definition_id) if grant else None
        level = ((((action.parameters or {}).get('typed') or {}).get('numbers') or {}).get('cl')) if action else None
        if type(level) is int and level <= cl + 2:
            out["temp_hp"] = ("temp_hp", "", "Temporary Hit Points", None)
    for key, item in target.modifiers.items():
        kind = 'modifier'
        level = end_effect.known_source_cl(ctx, item)
        if level is None or level > cl + 2:
            continue
        action = end_effect.source_action(ctx, item)
        source_typed = ((action.parameters or {}).get('typed') or {}) if action else {}
        if (kind == 'modifier' and item.target_field == 'damage_immunity' and _devour(ctx.engine, ctx.actor)
                and not source_typed.get('immunity_cannot_be_downgraded')
                and int(source_typed.get('immunity_downgrade_min_cl') or 0) <= cl):
            out[f'immunity_modifier:{key}'] = ('immunity_modifier', key,
                f'{str(item.value).title()} Immunity, treated as Resistance until the start of your next turn', None)
        if not ends_by_itself(item):
            continue
        if kind == "modifier" and item.target_field in PROTECTION_MODIFIER_FIELDS:
            if item.target_field.startswith('armor_class') and (type(item.value) is not int or item.value <= 0):
                continue
            label = f"{item.target_field.replace('_', ' ')} {item.value}".strip()
            out[f"modifier:{key}"] = (kind, key, label, None)
    for key, item in target.conditions.items():
        from ..typed_executor import is_active_typed_condition
        if not is_active_typed_condition(item):
            continue
        rule = end_effect.condition_rule(item, item.condition_id.removeprefix('condition:typed.'))
        level = end_effect.known_source_cl(ctx, item)
        if level is None or level > cl + 2 or not ends_by_itself(item):
            continue
        # Printed choices include "one Resistance" and "a temporary ward/barrier attached to the creature".
        # A temporary Resistance may arrive as a condition rule (the standard_conditions defense form) rather
        # than a damage_resistance modifier, so read the same declaration end_effect/insight readers use.
        resistances = [str(kind).upper() for kind in (rule.get('damage_resistances') or []) if isinstance(kind, str) and kind]
        if resistances and not rule.get('damage_immunities'):
            if 'ALL' in resistances:
                resistances = [*VALID, *PHYSICAL]  # resistance to every damage type: still one at a time
            for damage_type in dict.fromkeys(resistances):
                out[f'resistance:{key}:{damage_type}'] = ('resistance', key,
                    f'{damage_type.title()} Resistance', damage_type)
        elif rule.get('effect_kind') in PROTECTION_CONDITION_KINDS:
            out['condition:' + key] = ('condition', key, str(item.data.get('label') or 'Temporary ward'), None)
    if _devour(ctx.engine, ctx.actor):
        for row in (getattr(ctx.engine, 'typed_passive_rows', {}) or {}).get(target.entity_id, []):
            if row.get('block') not in ('resistance', 'defense') or row.get('kind') != 'immunity':
                continue
            level = (row.get('numbers') or {}).get('cl', row.get('cl'))
            feature = str(row.get('feature_id') or '')
            if (not feature or type(level) is not int or level > cl + 2 or row.get('immunity_cannot_be_downgraded')
                    or int(row.get('immunity_downgrade_min_cl') or 0) > cl):
                continue
            for damage_type in row.get('damage_types') or []:
                key = feature + '|' + str(damage_type).upper()
                out['immunity_feature:' + key] = ('immunity_feature', key,
                    f'{str(damage_type).title()} Immunity, treated as Resistance until the start of your next turn', None)
    return out


@hook('temp_hp_lifetime_required')
def preserve_feast_grant_lifetimes(ctx: Any, row: dict[str, Any]) -> bool | None:
    """Only a fight with an actual Feast owner needs suppressible grant clocks."""
    return True if any('feast' in raw_roles(ctx.engine, actor) for actor in ctx.engine.state.actors.values()) else None


@effect("maw_set_aside")
def set_aside(ctx: Any, row: dict[str, Any]) -> None:
    """Feast upon Protection: one protection is inactive until the start of the owner's next turn (restored then)."""
    from .needle import ask, checkpoint_id

    target = ctx.target
    if target is None or not target.active:
        return
    options = _protections(ctx, target)
    if not options:
        return
    picked = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, "feast_protection", target.entity_id), ctx.actor, "choice:needle.feast_protection",
                 list(options), labels={k: v[2] for k, v in options.items()},
                 prompt=f"Feast upon Protection: choose the protection {target.display_name} loses until the start of your next turn.",
                 target_id=target.entity_id)
    if not picked:
        return
    kind, key, _label, damage_type = options[picked[0]]
    if kind == 'resistance':
        # Suppress exactly the chosen Resistance: the condition keeps its other
        # Resistances, benefits and original duration, and is restored below.
        condition = target.conditions.get(key)
        if condition is None:
            return
        from . import end_effect
        from .retained_updates import record_instance_update
        rule = end_effect.condition_rule(condition, condition.condition_id.removeprefix('condition:typed.'))
        kinds = [str(kind).upper() for kind in (rule.get('damage_resistances') or [])]
        remaining = ([k for k in (*VALID, *PHYSICAL) if k != damage_type] if 'ALL' in kinds
                     else [k for k in kinds if k != damage_type])
        own = dict((condition.data or {}).get('rule') or {})
        own['damage_resistances'] = remaining
        condition.data = {**(condition.data or {}), 'rule': own}
        record_instance_update(ctx.engine, target, 'condition', key, condition)
        ctx.engine._apply_condition(target, SET_ASIDE, ctx.source, ctx.actor.entity_id, expires_on="UNTIL_REMOVED",
                                    data={"label": f"{str(damage_type).title()} Resistance set aside by Feast upon Protection",
                                          "resistance_condition": key, "resistance_type": damage_type})
        return
    if kind in ('immunity_modifier', 'immunity_feature'):
        if kind == 'immunity_modifier':
            damage_type = str(target.modifiers[key].value).upper()
            modifiers, features = [key], []
        else:
            feature, damage_type = key.rsplit('|', 1)
            modifiers, features = [], [feature]
        ctx.engine._apply_condition(target, DOWNGRADED, PREFIX + DEVOUR, ctx.actor.entity_id,
            expires_on='START_OF_SOURCE_NEXT_TURN', data={'modifier_ids': modifiers, 'feature_ids': features,
                'damage_type': damage_type,
                'label': f'{damage_type.title()} Immunity is treated as Resistance until the start of the Maw disciple\'s next turn'})
        return
    if kind == "temp_hp":
        from .temp_hp_grants import held_grant, lifetime_for
        held_grant_id = held_grant(ctx.engine.events, target.entity_id)
        grant = next((e for e in ctx.engine.events if held_grant_id is not None and e.sequence == held_grant_id[2]), None)
        before = int(target.temporary_hp)
        target.temporary_hp = 0
        ctx.engine._append_event("TEMP_HP_GRANTED", ctx.source, actor_id=ctx.actor.entity_id, target_ids=(target.entity_id,),
                                 payload={"offered": 0, "before": before, "after": 0, "removed_by": "Feast upon Protection"})
        record = {"temp_hp": before, 'temp_hp_source': grant.source_definition_id if grant else ctx.source,
                  'temp_hp_actor': str(grant.actor_id or target.entity_id) if grant else target.entity_id}
        lifetime = lifetime_for(target, held_grant_id[2]) if held_grant_id is not None else None
        if lifetime is not None:
            record['temp_hp_lifetime'] = lifetime.instance_id
    else:
        from .end_effect import suppress
        item = target.conditions[key] if kind == 'condition' else target.modifiers[key]
        suppress(target, kind, key, item, by=ctx.actor, engine=ctx.engine, boundary='start')
        return
    ctx.engine._apply_condition(target, SET_ASIDE, ctx.source, ctx.actor.entity_id, expires_on="UNTIL_REMOVED",
                                data={"label": "A protection set aside by Feast upon Protection", **record})


@hook('immunity_as_resistance')
def feast_downgraded_immunity(engine: Any, kind: str, typed: dict[str, Any], source_actor_id: str, target: Any) -> dict[str, Any] | None:
    if target is None:
        return None
    modifiers, features = [], []
    for condition in target.conditions.values():
        if condition.condition_id != DOWNGRADED or condition.data.get('damage_type') != kind:
            continue
        modifiers.extend(condition.data.get('modifier_ids') or [])
        features.extend(condition.data.get('feature_ids') or [])
    return {'modifier_ids': modifiers, 'feature_ids': features} if modifiers or features else None


@hook("turn_start")
def restore_protections(engine: Any, actor: Any) -> None:
    for holder in engine.state.actors.values():
        for held in [c for c in holder.conditions.values() if c.condition_id == SET_ASIDE and c.source_actor_id == actor.entity_id]:
            holder.conditions.pop(held.instance_id)
            engine._append_event("CONDITION_REMOVED", held.source_definition_id, actor_id=actor.entity_id, target_ids=(holder.entity_id,),
                                 payload={"condition_id": SET_ASIDE, "instance_id": held.instance_id})
            data = held.data or {}
            if data.get("resistance_condition") and data.get("resistance_type") and holder.active:
                condition = holder.conditions.get(data["resistance_condition"])
                if condition is not None:
                    own = dict((condition.data or {}).get('rule') or {})
                    kinds = [str(kind).upper() for kind in own.get('damage_resistances') or []]
                    if data["resistance_type"] not in kinds:
                        kinds.append(data["resistance_type"])
                    own['damage_resistances'] = kinds
                    condition.data = {**(condition.data or {}), 'rule': own}
                    from .retained_updates import record_instance_update
                    record_instance_update(engine, holder, 'condition', condition.instance_id, condition)
            if data.get("temp_hp") and holder.active:
                from .temp_hp_grants import rebind_lifetime
                lifetime_id = data.get('temp_hp_lifetime')
                lifetime = holder.conditions.get(lifetime_id) if lifetime_id else None
                if lifetime_id and lifetime is None:
                    continue  # the suppressed pool's own duration ended
                sequence = engine.state.event_sequence
                engine._grant_temp_hp(holder, int(data["temp_hp"]), data.get('temp_hp_source') or held.source_definition_id,
                                      data.get('temp_hp_actor') or actor.entity_id)
                if lifetime is not None:
                    rebind_lifetime(engine, holder, lifetime, after_sequence=sequence)


@effect("maw_break_defense")
def break_defense(ctx: Any, row: dict[str, Any]) -> None:
    """World-Eating Bite, failed save: end one temporary lasting effect helping the target; with none, strip its Temporary HP."""
    from . import end_effect
    from .needle import ask, checkpoint_id

    target = ctx.target
    if target is None or not target.active:
        return
    from .source_eligibility import ends_by_itself
    candidates = [('condition', key, item) for key, item in target.conditions.items()]
    candidates += [('modifier', key, item) for key, item in target.modifiers.items()]
    found = [(kind, key, item) for kind, key, item in candidates
             if ends_by_itself(item) and end_effect.known_source_cl(ctx, item) is not None
             and ((kind == 'modifier' and item.target_field in PROTECTION_MODIFIER_FIELDS) or
                  (kind == 'condition' and end_effect.condition_rule(item, item.condition_id.removeprefix('condition:typed.')).get('effect_kind') in
                   ENDABLE_CONDITION_KINDS))]
    if not found:
        if int(target.temporary_hp or 0) > 0:
            before = int(target.temporary_hp)
            target.temporary_hp = 0
            ctx.engine._append_event("TEMP_HP_GRANTED", ctx.source, actor_id=ctx.actor.entity_id, target_ids=(target.entity_id,),
                                     payload={"offered": 0, "before": before, "after": 0, "removed_by": "World-Eating Bite"})
        from ..typed_executor import run_effects
        run_effects(ctx, [{'type': 'deny_temp_hp', 'applies_to': 'target', 'expires_on': 'START_OF_SOURCE_NEXT_TURN'}])
        return
    ids = [f"{kind}:{key}" for kind, key, _item in found]
    labels = {}
    for kind, key, item in found:
        action = end_effect.source_action(ctx, item)
        label = str((getattr(item, 'data', None) or {}).get('label') or
                    (action.display_name if action is not None else 'Temporary defensive effect'))
        labels[f'{kind}:{key}'] = label
    picked = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, "world_bite", target.entity_id), ctx.actor, "choice:needle.world_bite", ids,
                 labels=labels, target_id=target.entity_id,
                 prompt=f"World-Eating Bite: choose one temporary effect on {target.display_name} to end now; its underlying source remains.")
    for kind, key, item in found:
        if picked and f"{kind}:{key}" == picked[0]:
            source_cl = end_effect.known_source_cl(ctx, item)
            if source_cl >= int(ctx.numbers.get('cl') or 1) + 3:
                # Body General Procedures R8 §4: normal resistance has already
                # resolved; superior authority additionally requires a native
                # Cultivation Check. Within two uses the printed CON save.
                from ..typed_executor import resolve_opposed_check
                source_actor = ctx.engine.state.actors.get(item.source_actor_id)
                dc = end_effect.cultivation_dc(ctx.engine, source_actor) if source_actor else 10 + source_cl // 2
                if not resolve_opposed_check(ctx, target,
                        {'kind': 'cultivation', 'label': 'World-Eating Bite against superior cultivation authority'},
                        {'kind': 'dc', 'dc': dc}).success:
                    return
            end_effect.remove_instance(ctx, target, kind, key, item)


# ------------------------------------------------------------------------------------------ Regurgitate Calamity
@effect("maw_regurgitate")
def regurgitate(ctx: Any, row: dict[str, Any]) -> None:
    from .. import typed_executor as te
    from .needle import ask, checkpoint_id

    engine, actor = ctx.engine, ctx.actor
    profile = effective_profile(engine, actor)
    ctx.typed = {**ctx.typed, 'numbers': {**ctx.numbers, **profile}}
    cache_key = '_maw_regurgitate_cost'
    cached = ctx.damage_cache.get(cache_key)
    if cached is not None:
        kind, count = cached
    else:
        types = stored(actor)
        if not types:
            return
        options = [f"{kind}:{n}" for kind in sorted(set(types)) for n in range(min(3, types.count(kind)), 0, -1)]
        picked = ask(engine, ctx.intent, checkpoint_id(engine, "regurgitate", actor.entity_id), actor, "choice:needle.regurgitate", options,
                     labels={o: f"{o.split(':')[1]} {o.split(':')[0].title()} Essence" for o in options},
                     prompt=f"Regurgitate Calamity: choose the Essence {actor.display_name} spends (one type, up to 3).", target_id=actor.entity_id)
        if not picked:
            return
        kind, count = picked[0].split(":")[0], int(picked[0].split(":")[1])
        spend(engine, actor, [kind] * count, ctx.source)
        ctx.damage_cache[cache_key] = (kind, count)
    dtype = kind.lower()
    if row.get("mode") == "line":
        te.run_effects(ctx, [{"type": "piercing_area", "all_creatures": True, 'scoped_origin': True, "effects": [
            {"type": "save", "ability": "dex", "applies_to": "creatures_in_area",
             "on_fail": [{"type": "damage", "applies_to": "creatures_in_area", "dice": {"count": 2 * count, "sides": 8}, "damage_types": [dtype]}],
             "on_success": [{"type": "half_damage", "applies_to": "creatures_in_area", "damage_types": [dtype]}]}]}])
    else:
        te.run_effects(ctx, [{"type": "attack", "attack_kind": "cultivation_ranged", "count": 1,
                              "on_hit": [{"type": "damage", "applies_to": "target", "dice": {"count": 3 * count, "sides": 8}, "damage_types": [dtype]}], "on_miss": []}])


@effect('maw_devour_state')
def devour_state(ctx: Any, row: dict[str, Any]) -> None:
    from .states import state
    ctx.typed = {**ctx.typed, 'numbers': {**ctx.numbers, **effective_profile(ctx.engine, ctx.actor)}}
    state(ctx, {**row, 'effect_kind': 'transformation'})


@hook("candidate_allowed")
def regurgitate_needs_essence(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    typed = ((getattr(action, "parameters", None) or {}).get("typed") or {}) if action is not None else {}
    if not any(isinstance(e, dict) and e.get("type") in ("maw_regurgitate", 'maw_expel') for e in typed.get("effects") or []):
        return None
    return None if stored(actor) else False


# ---------------------------------------------------------------------------------------- Devour Heaven and Earth
@hook("activation_settlement")
def devour_cp(ctx: Any, receipt: dict[str, Any]) -> None:
    """Once per round when a hostile creature within 60 feet spends CP, 1 Essence after its feature resolves."""
    from ..paid_relocation import current_activation
    from ..typed_executor import CP_POOLS
    payment = current_activation(ctx.engine)
    if (payment is None or payment.actor_id != ctx.actor.entity_id
            or payment.source_id != ctx.action.source_definition_id
            or sum(amount for pool, amount in payment.net_payments if pool in CP_POOLS) <= 0):
        return
    engine, user = ctx.engine, ctx.actor
    for owner in engine.state.actors.values():
        if not owner.active or farming_excluded(owner, user.entity_id) or owner.team_id == user.team_id or user.owner_id is not None or 'devour' not in _roles(engine, owner) or not _devour(engine, owner) or engine._distance_actor_to_actor(owner, user) > 60:
            continue
        if owner.turn_flags.get("_round_devour_cp") == int(engine.state.round_number):
            continue
        from .needle import ask, checkpoint_id
        options = receipt['dealt_damage_types'] or ['FORCE']
        typed = (ctx.action.parameters or {}).get('typed') or {}
        supernatural = (typed.get('supernatural') is True or typed.get('mundane') is False
                        or bool(typed.get('sphere') and not typed.get('weapon')))
        options = [t for t in options if t in VALID or (t in PHYSICAL and supernatural)]
        picked = ask(engine, ctx.intent, checkpoint_id(engine, 'devour_cp_type', owner.entity_id), owner,
                     'choice:needle.devour_cp_type', options,
                     labels={t: f"Store 1 {t.title()} Essence" for t in options},
                     prompt=f"Devour Heaven and Earth: {user.display_name} spent Cultivation Points on {ctx.action.display_name}. "
                            f"Choose the Essence {owner.display_name} gains after it resolves.")
        if picked and gain(engine, owner, picked[0], receipt['source_id'], normal=False,
                           source_cl=receipt['source_cl'], intent=ctx.intent):
            owner.turn_flags["_round_devour_cp"] = int(engine.state.round_number)
            note(engine, PREFIX + "devour_heaven_and_earth", owner, f"Devour Heaven and Earth: {owner.display_name} devours 1 Essence from {user.display_name}'s technique.")
