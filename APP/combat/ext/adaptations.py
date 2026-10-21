"""Heaven-Answering Adaptive Body: Damage and Affliction Adaptations (rider lane C7, 2026-09-30: "i want everything we can
automated").

Owned rows: ``path_passive`` kind ``adaptation`` with ``role``: "damage" (Flesh Remembers Pain), "affliction" (Meridians
Remember Affliction), "ten_thousand" (Ten Thousand Answers), "lesson" (Return the Lesson). The records are one condition on
the owner, ``condition:typed.adaptations`` (lists of strings: adapted damage types and conditions, each with the creature
that caused it; round numbers for the once-per-round acquisitions).

Damage Adaptation   once per round after hostile damage of a type reaches the owner's Hit Points, that type is adapted until
                    the fight ends (1 kept; 3 with Ten Thousand Answers). At capacity the owner is asked immediately
                    whether the newest replaces one (declining is legal; an AI owner replaces the oldest). While
                    adapted: the first packet of that type each round is reduced by Proficiency Bonus (Force/Psychic: twice
                    PB with Ten Thousand Answers, which also gives Resistance to the other adapted types). Flesh Remembers
                    Pain's Reaction only answers damage of an adapted type (row_allowed).
Affliction Adaptation  once per round after failing a hostile save that imposes Blinded, Charmed, Frightened, Paralyzed,
                    Poisoned, Restrained or Stunned, that condition is adapted (1 kept; 2 with Ten Thousand Answers; several
                    eligible or at capacity: selected immediately). While it bears the adapted condition: +PB
                    to saves made to end it (d20_bonus on a save from that condition's source), and at the end of its turn,
                    if the condition has no save of its own, it may spend 2 Stamina (asked, once per round) to repeat the
                    original save.
Return the Lesson   once per turn after hitting a creature recorded by an Adaptation, 1 Stamina (asked): +2d8 Force and one
                    result -- push 10 feet, no Reactions or Speed 0 until the start of its next turn, Disadvantage on its next
                    save against one of your Body Refining features before the end of your next turn, or move 10 feet
                    without provoking.
Shared public helpers: acquire is used by d20_rewrite_rules to persist a chosen
Affliction Adaptation even when Perfect Counter-Evolution's reroll succeeds.
ending_save_scope is shared with repeat_saves for explicit saves made to end a
condition. Native repeats enter the same scope through repeat_save_scope.
Everything is inert for a creature without these rows.
"""

from __future__ import annotations

from typing import Any
from contextlib import contextmanager
from contextvars import ContextVar

_ENDING_SAVE = ContextVar("adaptation_ending_save", default=None)

from . import hook, note

PREFIX = "tianxia.subpath.body.heaven_answering_adaptive_body.feature."
RECORD = "condition:typed.adaptations"
LESSON_SAVE = "condition:typed.lesson_save"
AFFLICTIONS = ("blinded", "charmed", "frightened", "paralyzed", "poisoned", "restrained", "stunned")
TYPES = ("ACID", "BLUDGEONING", "COLD", "FIRE", "FORCE", "LIGHTNING", "NECROTIC", "PIERCING", "POISON", "PSYCHIC", "RADIANT", "SLASHING", "THUNDER")
COUNTER = PREFIX + "perfect_counter_evolution"
COUNTER_ROUND = "_round_counter_evolution"
LEVELS = {"damage": 3, "affliction": 6, "lesson": 10, "ten_thousand": 14, "counter": 18}
FAMILY = PREFIX.removesuffix('.feature.')
PROHIBITED = frozenset({'bars_adaptation', 'willing_cost', 'self_damage', 'maximum_hp_loss',
                       'aging', 'realm_suppression', 'cl_reduction', 'permanent_identity_rewriting'})


def feature_available(engine: Any, actor: Any, role: str) -> bool:
    """Public effective-CL gate shared with the Counter-Evolution save consumer."""
    return role in _roles(engine, actor)


def qualifying_hostility(engine: Any, subject: Any, source_id: str, by: str) -> bool:
    """Collect the source controller's own unstaged purpose for this activation.

    Team, ownership and CL come from the native combat roster. Purpose is a
    declaration by the source, never inferred from a damage name or paid cost.
    The source's AI knows its own accepted hostile action; it never answers for
    a human controller. Explicit GM hazard/equivalent-threat declarations travel
    through the fact admission owner's world-input path instead.
    """
    from ..fact_consent_admission import combat_records, admit_choice
    from .activation_requirements import effective_cl
    from types import SimpleNamespace
    source = engine.state.actors.get(by)
    world = next((profile for bundle in engine.typed_bundle_documents if bundle['actor_id'] == subject.entity_id
                  for profile in bundle.get('adaptation_scene', {}).get('opposition', [])
                  if profile['source_id'] == source_id and profile['creature_id'] == ((by or '') if source is not None else '')
                  and profile['expires_after_round'] >= engine.state.round_number), None)
    if world is not None and not world['not_staged']:
        return False
    if source is None:
        return bool(world and world['active_hazard'] and world['not_staged'])
    if source is subject:
        return False
    template = engine.actor_templates.get(by)
    owners = {oid for oid in (getattr(template, 'owner_id', None), getattr(source, 'owner_id', None)) if oid}
    if subject.entity_id in owners:
        return False
    source_cl = effective_cl(source, next((int(b.get('cl') or 1) for b in engine.typed_bundle_documents if b['actor_id'] == by), 1), engine=engine)
    own_cl = effective_cl(subject, max((int(r.get('cl', 1)) for r in _roles(engine, subject).values()), default=1), engine=engine)
    if source_cl < own_cl - 5 and not (world and world['equivalent_threat'] and world['not_staged']):
        return False
    intent = _intent(engine)
    if intent is None:
        return False
    scope = subject.entity_id + ':' + str(source_id) + ':' + intent.intent_id
    known = combat_records(engine, subject, source=FAMILY, kind='qualifying_hostility', scope=scope)
    action = engine.action_catalog.get(source_id) or SimpleNamespace(display_name='the ongoing effect', source_definition_id=source_id)
    ctx = SimpleNamespace(engine=engine, actor=source, intent=intent, action=action)
    for owner_id in sorted(owners):
        master = engine.state.actors.get(owner_id)
        if master is None:
            return False  # missing native controller authority is not permission
        control_scope = scope + ':controller:' + master.entity_id
        control = combat_records(engine, subject, source=FAMILY, kind='control_qualification', scope=control_scope)
        control_options = (['willing_ally', 'not_willing_ally'] if master.team_id == subject.team_id
                           else ['not_willing_ally', 'willing_ally'])
        permission = control[-1] if control else admit_choice(ctx, master, FAMILY, 'control_qualification', control_scope,
            control_options,
            labels={'willing_ally': f'I am, or was when creating or controlling this creature, {subject.display_name}’s willing ally: no Adaptation',
                    'not_willing_ally': f'I was not {subject.display_name}’s willing ally when creating or controlling this creature'},
            prompt=f'Heaven-Answering Adaptive Body: {master.display_name}, are you now, or were you when creating or controlling {source.display_name}, {subject.display_name}’s willing ally? This declaration costs nothing.',
            expires_on=f"END_OF_SOURCE_TURN_AT:{int(master.turns_started) + int(engine.state.current_actor_id != master.entity_id)}",
            readers=(subject.entity_id,), automatic_options=control_options)
        if permission is None or permission['value'] != 'not_willing_ally':
            return False
    purpose_options = ['genuine', 'staged'] if source.team_id != subject.team_id else ['staged', 'genuine']
    record = known[-1] if known else admit_choice(ctx, source, FAMILY, 'qualifying_hostility', scope,
        purpose_options, labels={'genuine': 'Genuine hostile opposition, not staged to generate Adaptations',
                                 'staged': 'Friendly, accidental, willing, controlled, or staged contact: no Adaptation'},
        prompt=f'Heaven-Answering Adaptive Body: {source.display_name}, is your {action.display_name} against {subject.display_name} genuine hostile opposition? This records your purpose for this activation; it costs nothing.',
        expires_on=f"END_OF_SOURCE_TURN_AT:{int(source.turns_started) + int(engine.state.current_actor_id != source.entity_id)}",
        readers=(subject.entity_id,), automatic_options=purpose_options)
    if record is None or record['value'] != 'genuine':
        return False
    if world is not None and world['not_staged']:
        return True
    # The attacker cannot know whether the recipient deliberately captured,
    # revived or staged it to farm resources. Collect that owner's own fact,
    # rather than treating a hostile attack as proof about somebody else's plan.
    received = combat_records(engine, subject, source=FAMILY, kind='anti_farming', scope=scope)
    recipient_ctx = SimpleNamespace(engine=engine, actor=source, intent=intent,
                                    action=SimpleNamespace(display_name='the incoming effect'))
    honest = received[-1] if received else admit_choice(recipient_ctx, subject, FAMILY, 'anti_farming', scope,
        ['not_farmed', 'farmed_or_unknown'],
        labels={'not_farmed': 'This is genuine danger, not willing training, self harm, or a captured/revived/staged resource farm',
                'farmed_or_unknown': 'This was arranged to farm Adaptations, or I cannot establish that it qualifies: no Adaptation'},
        prompt=f'Heaven-Answering Adaptive Body: {subject.display_name}, confirm that this event was not arranged through willing allies, controlled creatures, harmless contact, or a deliberately captured, revived or staged foe to generate Adaptations. This declaration costs nothing.',
        expires_on=f"END_OF_SOURCE_TURN_AT:{int(subject.turns_started) + int(engine.state.current_actor_id != subject.entity_id)}",
        automatic_options=['not_farmed', 'farmed_or_unknown'])
    return honest is not None and honest['value'] == 'not_farmed'


@hook('fact_admission_schema')
def opposition_schema(session: Any, source: str, subject: str, kind: str) -> dict[str, Any] | None:
    actor = session.state['actors'].get(subject)
    if (source == FAMILY and kind == 'opposition' and actor is not None
            and any(str(r.get('feature_id', '')).startswith(PREFIX) for r in actor.get('bundle', {}).get('typed_passives', []))):
        return {'value_type': 'document', 'maximum_seconds': 3600, 'authority': 'table_owner',
                'description': 'The table owner identifies a genuine active hazard or equivalent encounter threat for this scene.'}
    return None


@hook('journey_combat_bundle')
def opposition_bundle(bundle: dict[str, Any], session: Any, actor_id: str) -> dict[str, Any]:
    """Freeze authorized scene declarations into the real encounter bundle.

    A declaration never causes damage, grants a row, or fabricates a source.
    Damage/save events must still match its exact source and legal creature.
    """
    if not any(str(r.get('feature_id', '')).startswith(PREFIX) for r in bundle.get('typed_passives', [])):
        return bundle
    from ..fact_consent_admission import read
    from ..journey import require
    scene = session.state.get('scene_id', session.state['journey_id'])
    scopes = {r['scope'] for r in session.state.get('fact_consent_admission', [])
              if r['source'] == FAMILY and r['subject'] == actor_id and r['kind'] == 'opposition'}
    profiles = []
    for scope in sorted(scopes):
        receipt = read(session, FAMILY, actor_id, 'opposition', scope, actor_id)
        if receipt is None or not scope.startswith(scene + ':'):
            continue
        value = receipt['value']
        require(set(value) == {'source_id', 'creature_id', 'active_hazard', 'not_staged', 'equivalent_threat'},
                'Name the exact source, creature (or empty for a hazard), active hazard, unstaged opposition and equivalent-threat flags.')
        require(type(value['source_id']) is str and bool(value['source_id'])
                and scope == scene + ':' + value['source_id']
                and type(value['creature_id']) is str
                and (value['creature_id'] == '' or value['creature_id'] in session.state['actors'])
                and all(type(value[k]) is int and value[k] in (0, 1)
                        for k in ('active_hazard', 'not_staged', 'equivalent_threat')),
                'Use the current scene, a legal creature or active hazard, and whole yes/no flags.')
        profiles.append({**value, 'expires_after_round': max(0, (receipt['expires_at'] - int(session.clock())) // 6),
                         'receipt_id': receipt['receipt_id'], 'authority': receipt['authority']})
    return {**bundle, 'adaptation_scene': {'scene_id': scene, 'opposition': profiles}}


def _roles(engine: Any, actor: Any) -> dict[str, dict[str, Any]]:
    from .activation_requirements import effective_cl
    return {str(row.get("role")): row for row in (getattr(engine, "typed_passive_rows", {}) or {}).get(actor.entity_id, [])
            if row.get("block") == "path_rider" and row.get("kind") == "adaptation"
            and effective_cl(actor, row.get("cl", 1), engine=engine) >= LEVELS.get(row.get("role"), 99)}


def active_records(engine: Any, actor: Any, category: str) -> list[dict[str, Any]]:
    """Public, pure read of maintained records whose creating feature is available.

    Suppression suspends benefits without deleting records or refunding clocks.
    Used by the family damage, ending-save and counterattack consumers.
    """
    from .activation_requirements import effective_cl
    role = "damage" if category == "damage" else "affliction"
    roles = _roles(engine, actor)
    if role not in roles and "counter" not in roles:
        return []
    cl = max((int(row.get("cl", 1)) for row in roles.values()), default=1)
    return [row for row in _record(actor).get(category, [])
            if effective_cl(actor, cl, engine=engine) >= max(int(row.get("minimum_cl", LEVELS[role])),
                                                          int(row.get('capacity_minimum_cl', 0)))]


def packet_adaptable(engine: Any, actor: Any, source: Any, by: Any, flags=()) -> bool:
    """Use the real pending packet's flags; prices and self harm never qualify.

    Explicit source restrictions remain absolute. This query is also used by
    defense consumers, so a forbidden packet cannot benefit from an old record.
    """
    from ..pending_damage import current
    pending = current(engine)
    flags = (*flags, *(pending.source_flags if pending is not None else ()))
    action = engine.action_catalog.get(source)
    typed = (action.parameters.get("typed") or {}) if action is not None else {}
    return (by != actor.entity_id and not typed.get("bars_adaptation")
            and not PROHIBITED.intersection(flags))


@hook('journey_scene_end')
def expire_scene(session: Any, previous_scene: str, next_scene: str) -> None:
    """Consume the native table-owner scene boundary; never treat rest as expiry.

    Encounter snapshots are the shared journey continuation format. Remove only
    this family's records/riders; wounds, hostile conditions and other sources
    remain the continuation owner's responsibility.
    """
    import json
    for actor in session.state['actors'].values():
        snapshot = actor.get('encounter_snapshot') or {}
        held = snapshot.get('conditions') or {}
        for iid, encoded in list(held.items()):
            condition = json.loads(encoded)
            declaration = (condition.get('data') or {}).get('record')
            own_declaration = declaration and json.loads(declaration).get('source') == FAMILY
            if condition['condition_id'] in (RECORD, LESSON_SAVE) or own_declaration:
                del held[iid]
                session.emit('ADAPTATION_EXPIRED', next(aid for aid, value in session.state['actors'].items() if value is actor),
                             source=condition['source_definition_id'], previous_scene=previous_scene)


def _record(actor: Any) -> dict[str, Any]:
    held = next((c for c in actor.conditions.values() if c.condition_id == RECORD), None)
    return dict((held.data or {}) if held is not None else {})


@hook('compile_action')
def collect_body_feature_names(action: Any, info: dict[str, Any]) -> Any:
    """Publish the actual owned Body feature names on the ordinary unarmed anchor.

    Return the Lesson may name passive or dormant features too. Action menus
    alone are not an ownership catalogue. This metadata grants no action or
    feature and is absent without Return the Lesson; its caller remains gated
    by the live effective CL. Native acquired tiers are bounded by attainment,
    never by future progression entries or guessed sphere ownership.
    """
    if PREFIX + 'return_the_lesson' not in info['owned_ids']:
        return action
    parameters = dict(action.parameters or {})
    if (parameters.get('typed') or {}).get('source') != 'unarmed_strike':
        return action
    from copy import deepcopy
    from pathlib import Path
    from ..subpath_acquisition import acquired_features
    physical = deepcopy(info['owner_sheet'])
    (physical.get('identity') or {}).pop('effective_cl', None)
    for row in (physical.get('path_and_subpath') or {}).get('paths') or []:
        if isinstance(row, dict):
            row.pop('effective_cl', None)
    owned = set(info['owned_ids']) | set(acquired_features(physical, Path(__file__).resolve().parents[2]))
    names = {mid: str(info['mechanics'][mid]['name']) for mid in sorted(owned)
             if mid in info['mechanics'] and mid.startswith(('tianxia.subpath.body.', 'tianxia.path.body_refining.'))}
    return action.model_copy(update={'parameters': {**parameters, 'adaptation_body_features': names}})


def _save_record(engine: Any, actor: Any, data: dict[str, Any], source: str) -> None:
    held = next((c for c in actor.conditions.values() if c.condition_id == RECORD), None)
    if held is not None:
        actor.conditions.pop(held.instance_id)
        engine._append_event("CONDITION_REMOVED", source, actor_id=actor.entity_id, target_ids=(actor.entity_id,),
                             payload={"condition_id": RECORD, "instance_id": held.instance_id})
    kinds = [row["type"].title() for row in data.get("damage") or []]
    afflictions = [row["condition"].title() for row in data.get("afflictions") or []]
    roles = _roles(engine, actor)
    pb = int(actor.proficiency_bonus or 2)
    advanced = bool({'ten_thousand', 'counter'}.intersection(roles))
    benefits = [f"{kind}: " + ('Resistance; ' if advanced and kind.upper() not in ('FORCE', 'PSYCHIC') else '')
                + f"reduce its first damage each round by {2 * pb if advanced and kind.upper() in ('FORCE', 'PSYCHIC') else pb}"
                for kind in kinds]
    if afflictions:
        benefits.append(', '.join(afflictions) + f': +{pb} to saves to end it; spend 2 Stamina at turn end to repeat its original save if it normally offers none that turn')
    data['label'] = ('Until scene end: ' + '; '.join(benefits)
                     + '. Benefits pause while their granting feature is unavailable.') if benefits else 'Adaptations: none yet'
    engine._apply_condition(actor, RECORD, source, actor.entity_id, expires_on="UNTIL_REMOVED", data=data)
    _sync_resistance(engine, actor)


def _capacity(engine: Any, actor: Any, kind: str) -> int:
    roles = _roles(engine, actor)
    if kind == "damage":
        return 3 if {"ten_thousand", "counter"}.intersection(roles) else 1 if "damage" in roles else 0
    return 2 if {"ten_thousand", "counter"}.intersection(roles) else 1 if "affliction" in roles else 0


def acquire(engine: Any, actor: Any, category: str, record: dict[str, Any], *, source: str) -> bool:
    """Record one selected Adaptation immediately, with an explicit replacement choice at capacity."""
    from .needle import ask, checkpoint_id

    key = 'type' if category == 'damage' else 'condition'
    if (category not in {'damage', 'afflictions'} or record.get(key) not in (TYPES if category == 'damage' else AFFLICTIONS)
            or source not in {COUNTER, PREFIX + ('flesh_remembers_pain' if category == 'damage' else 'meridians_remember_affliction')}):
        raise ValueError('An Adaptation requires its exact category, valid type or condition, and granting feature.')

    roles = _roles(engine, actor)
    role = "counter" if source == COUNTER else "damage" if category == "damage" else "affliction"
    if role not in roles or _capacity(engine, actor, category) <= 0:
        return False
    from .activation_requirements import effective_cl
    record = {**record, "source_cl": effective_cl(actor, roles[role].get("cl", 1), engine=engine),
              "granting_feature": source,
              "minimum_cl": LEVELS[role], "acquisition_round": int(engine.state.round_number),
              "acquisition_match": engine.state.match_id,
              "expires": "scene_end", "reduction_round": -1}
    if category == 'damage':
        record['reduction_round'] = int(actor.turn_flags.get('_round_adapted_first_' + record['type'], -1))
    data = _record(actor)
    key = "type" if category == "damage" else "condition"
    rows = list(data.get(category) or [])
    existing = next((row for row in rows if row[key] == record[key]), None)
    if existing is not None:
        if all(existing.get(k) == record.get(k) for k in ('by', 'source', 'source_cl', 'granting_feature')):
            return False
        picked = ask(engine, _intent(engine), checkpoint_id(engine, 'adapt_replace_' + category, actor.entity_id), actor,
                     'choice:needle.adapt_replace_' + category, [record[key]], allow_decline=source != COUNTER,
                     labels={record[key]: f'Replace the previous {record[key].title()} Adaptation with this new record'},
                     prompt=f'{actor.display_name}: keep the previous {record[key].title()} Adaptation, or replace it with this newly acquired record?')
        if not picked:
            return False
        record['capacity_minimum_cl'] = int(existing.get('capacity_minimum_cl', 0))
        record['reduction_round'] = int(existing.get('reduction_round', -1))
        rows = [record if row[key] == record[key] else row for row in rows]
    elif len(rows) < _capacity(engine, actor, category):
        record['capacity_minimum_cl'] = 14 if rows else 0
        rows.append(record)
    else:
        options = [row[key] for row in rows]
        picked = ask(engine, _intent(engine), checkpoint_id(engine, "adapt_replace_" + category, actor.entity_id),
                     actor, "choice:needle.adapt_replace_" + category, options, allow_decline=source != COUNTER,
                     labels={o: f"Replace {o.title()} with {record[key].title()}" for o in options},
                     prompt=f"{actor.display_name}: choose which Adaptation to replace with {record[key].title()}.")
        if not picked:
            return False
        rows = [{**record, 'capacity_minimum_cl': int(row.get('capacity_minimum_cl', 0))}
                if row[key] == picked[0] else row for row in rows]
    data[category] = rows
    if source != COUNTER:
        prefix = 'damage' if category == 'damage' else 'affliction'
        data[prefix + '_round'] = int(engine.state.round_number)
        data[prefix + '_match'] = engine.state.match_id
    _save_record(engine, actor, data, source)
    return True


@hook("before_damage_defenses")
def adaptation_response(engine: Any, actor: Any, amount: int, kind: str, source: Any, by: Any) -> list[dict[str, Any]] | None:
    from .needle import ask, checkpoint_id
    from ..typed_reactions import spend_reaction, can_use_reaction

    roles = _roles(engine, actor)
    # The knowledge permission is independent of Reaction availability and cost.
    # The private native choice contains only the adapted type, never a damage
    # amount, other types, hidden riders or the source's technique description.
    if (kind in {row['type'] for row in active_records(engine, actor, 'damage')}
            and packet_adaptable(engine, actor, source, by) and _intent(engine) is not None):
        ask(engine, _intent(engine), checkpoint_id(engine, 'adapt_notice', actor.entity_id), actor,
            'choice:needle.adapt_notice', ['continue'], labels={'continue': 'Continue'}, preferred=['continue'],
            name='Flesh Remembers Pain', feature_id=PREFIX + 'flesh_remembers_pain',
            prompt_context={'cost': 'No cost; no Action or Reaction.'},
            prompt=f'Flesh Remembers Pain: {actor.display_name}, the pending damage includes your adapted {kind.title()} type.')
    attacker = engine.state.actors.get(by)
    if (kind not in TYPES or not packet_adaptable(engine, actor, source, by)
            or not actor.reaction_available):
        return None
    new = kind not in {row['type'] for row in active_records(engine, actor, 'damage')}
    counter = new and "counter" in roles and actor.turn_flags.get(COUNTER_ROUND) != engine.state.round_number
    flesh = not new and "damage" in roles and actor.turn_flags.get("_round_flesh_response") != engine.state.round_number
    if not counter and not flesh:
        return None
    if counter and not qualifying_hostility(engine, actor, source, by):
        return None
    feature = COUNTER if counter else PREFIX + "flesh_remembers_pain"
    price = 2 if counter else 1
    if (actor.resources.get("resource:core.stamina", 0) < price
            or not can_use_reaction(engine, actor, attacker, {"feature_id": feature, "adaptation_response": True})):
        return None
    chosen = ask(engine, _intent(engine), checkpoint_id(engine, "adapt_response", actor.entity_id), actor,
                 "choice:needle.adapt_response", ["use"], allow_decline=True,
                 labels={"use": f"Spend {price} Stamina and your Reaction"},
                 name='Perfect Counter-Evolution' if counter else 'Flesh Remembers Pain', feature_id=feature,
                 prompt_context={'cost': f'{price} Stamina and your Reaction', 'paying_pool': 'resource:core.stamina'},
                 prompt=f"{'Perfect Counter-Evolution' if counter else 'Flesh Remembers Pain'}: {actor.display_name} faces {kind.title()} damage. Spend {price} Stamina and your Reaction to {'adapt before it lands' if counter else 'gain Resistance for this damage'}?")
    if not chosen:
        return None
    engine._spend_resource(actor, "resource:core.stamina", price, feature)
    spend_reaction(engine, actor, {"feature_id": feature, "adaptation_response": True})
    actor.turn_flags[COUNTER_ROUND if counter else "_round_flesh_response"] = engine.state.round_number
    if counter:
        acquire(engine, actor, "damage", {"type": kind, "by": by or "", "source": source or ""}, source=feature)
    engine._append_event("REACTION_RESOLVED", feature, actor_id=actor.entity_id,
                         target_ids=(actor.entity_id,), payload={"checkpoint": "BEFORE_DAMAGE_DEFENSES", "damage_type": kind})
    # Counter's CL14 benefit is synchronized by acquire; Force/Psychic get only
    # their normal first-instance flat reduction, never packet Resistance.
    from .activation_requirements import effective_cl
    return [] if counter else [{"kind": "resistance", "feature_id": feature,
        "protection_authority": {'origin': 'cultivated', 'authority': 'ordinary',
            'source_cl': effective_cl(actor, roles['damage'].get('cl', 1), engine=engine)}}]


def adapted_types(actor: Any) -> set[str]:
    return {str(row["type"]).upper() for row in _record(actor).get("damage") or []}


def _sync_resistance(engine: Any, actor: Any) -> None:
    """Remove obsolete materialized defenses; the live query handles dormancy."""
    source = PREFIX + "ten_thousand_answers"
    want = set()
    have = {m.value: mid for mid, m in actor.modifiers.items() if m.source_definition_id == source and m.target_field == "damage_resistance"}
    for kind, mid in have.items():
        if kind not in want:
            del actor.modifiers[mid]
            engine._append_event("MODIFIER_REMOVED", source, actor_id=actor.entity_id, target_ids=(actor.entity_id,),
                                 payload={"modifier_id": mid, "reason": "ADAPTATION_REPLACED"})


@hook("damage_defenses")
def adapted_resistance(engine: Any, actor: Any, kind: str, typed: Any, by: Any) -> list[dict[str, Any]] | None:
    if (not {"ten_thousand", "counter"}.intersection(_roles(engine, actor))
            or not packet_adaptable(engine, actor, (typed or {}).get('source'), by)):
        return None
    return [{"kind": "resistance", "damage_types": [row['type']], 'feature_id': PREFIX + 'ten_thousand_answers',
             'protection_authority': {'origin': 'cultivated', 'authority': 'ordinary', 'source_cl': int(row['source_cl'])}}
            for row in active_records(engine, actor, 'damage')
            if row['type'] not in ('FORCE', 'PSYCHIC')]


def _intent(engine: Any) -> Any:

    return getattr(engine, "_active_intent", None)


# ------------------------------------------------------------------------------------------------- acquiring records
@hook("event")
def damage_adaptation(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    if event_type != "DAMAGE_COMMITTED":
        return
    payload = kwargs.get("payload") or {}
    kind = str(payload.get("damage_type") or "").upper()
    by = str(kwargs.get("actor_id") or "")
    from ..damage_provenance import grouped_notification_pending
    if grouped_notification_pending(engine, kwargs.get('source_definition_id'), by):
        return
    if int(payload.get("hp_damage") or 0) < 1 or kind not in TYPES or payload.get("gate_damage"):
        return
    for target_id in kwargs.get("target_ids") or ():
        actor = engine.state.actors.get(target_id)
        source = engine.state.actors.get(by)
        if (actor is None or not packet_adaptable(engine, actor, kwargs.get('source_definition_id'), by)
                or "damage" not in _roles(engine, actor)):
            continue
        data = _record(actor)
        if data.get('damage_match') == engine.state.match_id and int(data.get("damage_round") or -1) == int(engine.state.round_number):
            continue
        if not qualifying_hostility(engine, actor, kwargs.get('source_definition_id'), by):
            continue
        acquire(engine, actor, "damage", {"type": kind, "by": by,
                "source": str(kwargs.get('source_definition_id') or '')}, source=PREFIX + "flesh_remembers_pain")


@hook('damage_dealt')
def remember_damage_packet(ctx: Any, subject: Any, amount: int) -> None:
    """Choose from the native completed hit's real HP-damaging components."""
    engine = ctx.engine
    if (not feature_available(engine, subject, 'damage')
            or not packet_adaptable(engine, subject, ctx.damage_source, ctx.actor.entity_id)
            or (_record(subject).get('damage_match') == engine.state.match_id
                and _record(subject).get('damage_round') == engine.state.round_number)):
        return
    banned = PROHIBITED
    options = sorted({str(p.get('damage_type', '')).upper() for p in ctx.damage_packets
                      if int(p.get('hp_damage') or 0) > 0 and not banned.intersection(p.get('source_flags') or ())
                      and str(p.get('damage_type', '')).upper() in TYPES})
    if not options:
        return
    if not qualifying_hostility(engine, subject, ctx.damage_source, ctx.actor.entity_id):
        return
    from .needle import ask, checkpoint_id
    picked = ask(engine, ctx.intent, checkpoint_id(engine, 'adapt_damage', subject.entity_id), subject,
                 'choice:needle.adapt_damage', options, labels={o: o.title() for o in options}, preferred=options[:1],
                 prompt=f'Flesh Remembers Pain: {ctx.action.display_name} damaged {subject.display_name}. Choose one damage type to adapt to until the scene ends.')
    if picked:
        acquire(engine, subject, 'damage', {'type': picked[0], 'by': ctx.actor.entity_id, 'source': ctx.damage_source},
                source=PREFIX + 'flesh_remembers_pain')


def _new_affliction_carriers(ctx: Any, subject: Any) -> list[Any]:
    """Find conditions from this failed save, including a separate native carrier."""
    start = int(ctx.damage_cache.get("adapt_save_start", 0))
    return [condition for condition in subject.conditions.values()
            if condition.condition_id.removeprefix("condition:typed.") in AFFLICTIONS
            and condition.applied_sequence > start
            and (condition.source_definition_id == ctx.source
                 or condition.source_actor_id == ctx.actor.entity_id)]


@hook("save_effects_settled")
def affliction_adaptation(ctx: Any, subject: Any, ability: str, failed: bool) -> None:
    if (subject is None or not failed or not ctx.origin_save
            or "affliction" not in _roles(ctx.engine, subject)
            or not packet_adaptable(ctx.engine, subject, ctx.source, ctx.actor.entity_id, ctx.damage_source_flags)):
        return
    # A typed save can apply its condition through a carrier feature (for
    # example Poison Touch), so the condition's source id need not be the
    # save action's source id. The fresh sequence and actual hostile source
    # actor bind the condition to this just-resolved save.
    carriers = _new_affliction_carriers(ctx, subject)
    eligible = sorted({c.condition_id.removeprefix("condition:typed.") for c in carriers})
    if not eligible:
        return
    data = _record(subject)
    if data.get('affliction_match') == ctx.engine.state.match_id and int(data.get("affliction_round") or -1) == int(ctx.engine.state.round_number):
        return
    if not qualifying_hostility(ctx.engine, subject, ctx.source, ctx.actor.entity_id):
        return
    from .needle import ask, checkpoint_id
    picked = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, "adapt_affliction", subject.entity_id), subject,
                 "choice:needle.adapt_affliction", eligible, preferred=eligible[:1], labels={name:name.title() for name in eligible},
                 prompt=f"Meridians Remember Affliction: choose {subject.display_name}'s Affliction Adaptation from the conditions this save imposed.")
    if not picked:
        return
    carrier = next(c for c in carriers if c.condition_id == "condition:typed." + picked[0])
    acquire(ctx.engine, subject, "afflictions", {"condition": picked[0],
            "by": carrier.source_actor_id or ctx.actor.entity_id,
            "source": carrier.source_definition_id,
            "imposing_source_cl": int(ctx.numbers.get('cl') or 1),
            **ctx.origin_save}, source=PREFIX + "meridians_remember_affliction")


@hook("after_save_resolved")
def remember_save_start(ctx: Any, subject: Any, ability: str, named: Any, failed: bool) -> None:
    # The shared damage cache is resolution-local and copied into this save's
    # outcome context. Only newly applied conditions qualify for acquisition.
    if subject is not None and feature_available(ctx.engine, subject, 'affliction'):
        ctx.damage_cache["adapt_save_start"] = ctx.engine.state.event_sequence


# -------------------------------------------------------------------------------------------------------- benefits
@hook("damage_reduction")
def first_instance(engine: Any, target: Any, damage_type: str, typed: Any, source_actor_id: Any, applied: bool = False) -> int | None:
    kind = str(damage_type).upper()
    if (kind not in {row['type'] for row in active_records(engine, target, 'damage')}
            or not packet_adaptable(engine, target, (typed or {}).get('source'), source_actor_id)):
        return None
    flag = "_round_adapted_first_" + kind
    if target.turn_flags.get(flag) == int(engine.state.round_number):
        return None
    pb = int(_roles(engine, target).get("damage", {}).get("pb") or target.proficiency_bonus or 2)
    amount = 2 * pb if kind in ("FORCE", "PSYCHIC") and {"ten_thousand", "counter"}.intersection(_roles(engine, target)) else pb
    if applied:
        target.turn_flags[flag] = int(engine.state.round_number)
        data = _record(target)
        for row in data.get('damage', []):
            if row['type'] == kind:
                row['reduction_round'] = int(engine.state.round_number)
        _save_record(engine, target, data, PREFIX + 'flesh_remembers_pain')
    return amount


@hook("row_allowed")
def adapted_reaction(engine: Any, actor: Any, row: dict[str, Any]) -> bool | None:
    """Flesh Remembers Pain's Reaction answers only damage of an adapted type."""
    if str(row.get("feature_id") or "") not in {PREFIX + "flesh_remembers_pain", COUNTER}:
        return None
    if row.get("adaptation_response"):
        return None
    return False if row.get("effects") else None  # generic damage rows only; d20 windows remain legal


@contextmanager
def ending_save_scope(engine: Any, actor: Any, condition: Any):
    """Bound ending-save provenance; native repeats and Meridians' own repeat share it."""
    origin = (condition.data or {}).get('origin_save') or {}
    tags = [*(origin.get('named') or ()), *('source_flag:' + flag for flag in origin.get('source_flags') or ())]
    token = _ENDING_SAVE.set((engine, actor.entity_id, condition.condition_id, condition.source_definition_id,
                              tuple(tags), condition.source_actor_id))
    try:
        yield
    finally:
        _ENDING_SAVE.reset(token)


def ending_save_active(engine: Any, actor: Any) -> bool:
    """Public provenance guard: failing an ending save imposes no new affliction."""
    scope = _ENDING_SAVE.get()
    return bool(scope and scope[0] is engine and scope[1] == actor.entity_id)


@hook("repeat_save_scope")
def native_ending_scope(engine: Any, resolution: dict[str, Any]) -> Any:
    actor = engine.state.actors.get(resolution["holder_id"])
    if actor is None or not _roles(engine, actor):
        return None
    condition = actor.conditions.get(resolution["instance_id"]) if actor else None
    return ending_save_scope(engine, actor, condition) if condition is not None else None


@hook("d20_bonus")
def end_the_affliction(engine: Any, roll: Any, intent: Any) -> dict[str, Any] | None:
    ending = _ENDING_SAVE.get()
    if not ending or ending[0] is not engine or ending[1] != roll.actor_id or not str(roll.reason).startswith("SAVE:"):
        return None
    if {str(tag).removeprefix('source_flag:') for tag in ending[4]}.intersection(PROHIBITED):
        return None
    actor = engine.state.actors.get(roll.actor_id)
    if actor is not None and any("condition:typed." + row["condition"] == ending[2]
                                 and row.get("source") == ending[3]
                                 and row.get("by") == ending[5]
                                 for row in active_records(engine, actor, "afflictions")):
        return {"source_id": PREFIX + "meridians_remember_affliction", "bonus": int(actor.proficiency_bonus or 2)}
    return None


def _repeatable_afflictions(actor: Any, rows: list[dict[str, Any]]) -> list[tuple[str, Any, dict[str, Any]]]:
    """Return exact recorded affliction carriers lacking their own turn save."""
    return [(iid, condition, row) for row in rows for iid, condition in actor.conditions.items()
            if condition.condition_id == "condition:typed." + row["condition"]
            and condition.source_definition_id == row.get('source')
            and condition.source_actor_id == row.get('by')
            and not (bool((condition.data or {}).get('repeat_save'))
                     and isinstance(condition.data.get('repeat_save'), dict)
                     and condition.data['repeat_save'].get('when', 'end') in ('start', 'end'))]


@hook("turn_end")
def repeat_without_a_save(engine: Any, actor: Any) -> None:
    rows = active_records(engine, actor, "afflictions") if feature_available(engine, actor, 'affliction') else []
    if not rows or actor.resources.get("resource:core.stamina", 0) < 2 or actor.turn_flags.get("_round_meridian_repeat") == int(engine.state.round_number):
        return
    from .repeat_saves import save_of

    held = _repeatable_afflictions(actor, rows)
    if not held:
        return
    from .needle import ask, checkpoint_id

    picked = ask(engine, _intent(engine), checkpoint_id(engine, "meridian_repeat", actor.entity_id), actor, "choice:needle.meridian_repeat",
                 [iid for iid, _c, _row in held], allow_decline=True, labels={iid: f"Spend 2 Stamina: repeat the save against {c.condition_id.rsplit('.', 1)[-1].title()}"
                                                                        for iid, c, _row in held},
                 prompt=f"Meridians Remember Affliction: {actor.display_name} may spend 2 Stamina to repeat the original save.", target_id=actor.entity_id)
    if not picked:
        return
    iid, condition, original = next(pair for pair in held if pair[0] == picked[0])
    actor.turn_flags["_round_meridian_repeat"] = int(engine.state.round_number)
    engine._spend_resource(actor, "resource:core.stamina", 2, PREFIX + "meridians_remember_affliction")
    save = save_of(condition) or original
    # Rules Reference fallback Authority DC: Mortal/Foundation/Core/Nascent/Immortal.
    # Source CL is the imposing effect's recorded authority, not the practitioner's.
    source_cl = int(original.get('imposing_source_cl') or 1)
    fallback_dc = next(dc for maximum, dc in ((4, 12), (9, 14), (14, 16), (19, 18), (40, 20)) if source_cl <= maximum)
    dc = save['dc'] if type(save.get('dc')) is int else fallback_dc
    engine.resolve_repeat_save(actor, iid, condition, {'ability': str(save['ability']).upper(), 'dc': dc},
                               'Meridians Remember Affliction')


# ------------------------------------------------------------------------------------------------- Return the Lesson
def _teachers(engine: Any, actor: Any) -> set[str]:
    return {row["by"] for category in ('damage', 'afflictions') for row in active_records(engine, actor, category)
            if row.get("by") in engine.state.actors}


@hook("after_hit")
def return_the_lesson(ctx: Any, target: Any, kind: str) -> None:
    engine, actor = ctx.engine, ctx.actor
    if target is None or "lesson" not in _roles(engine, actor) or target.entity_id not in _teachers(engine, actor):
        return
    stamp = f"{engine.state.round_number}:{engine.state.current_actor_id}"
    if actor.turn_flags.get("_round_return_lesson") == stamp or actor.resources.get("resource:core.stamina", 0) < 1:
        return
    from .needle import ask, checkpoint_id

    options = {"push": f"Push {target.display_name} 10 feet", "no_reactions": f"{target.display_name} takes no Reactions until the start of its next turn",
               "speed": f"{target.display_name}'s Speed is 0 until the start of its next turn",
               "save": f"{target.display_name} has Disadvantage on its next save against one named Body Refining feature before your next turn ends",
               "move": "Move 10 feet without provoking"}
    picked = ask(engine, ctx.intent, checkpoint_id(engine, "return_lesson", target.entity_id), actor, "choice:needle.return_lesson", list(options),
                 allow_decline=True, labels=options, target_id=target.entity_id,
                 prompt=f"Return the Lesson: {ctx.action.display_name} hit {target.display_name}; spend 1 Stamina for +{4 if 'counter' in _roles(engine, actor) else 2}d8 Force and one result?")
    if not picked:
        return
    actor.turn_flags["_round_return_lesson"] = stamp
    engine._spend_resource(actor, "resource:core.stamina", 1, PREFIX + "return_the_lesson")
    from .. import typed_executor as te

    sub = ctx.on_hit_context(target, action=ctx.action, typed=ctx.typed, damage_cache={})
    rows = [{"type": "extra_damage", "applies_to": "target", "dice": {"count": 4 if "counter" in _roles(engine, actor) else 2, "sides": 8}, "damage_types": ["force"],
             "evidence": f"Return the Lesson: +{4 if 'counter' in _roles(engine, actor) else 2}d8 Force"}]
    choice = picked[0]
    if choice == "push":
        rows.append({"type": "forced_movement", "applies_to": "target", "distance_ft": 10, "direction": "away"})
    elif choice == "no_reactions":
        rows.append({"type": "reaction_denied", "applies_to": "target", "expires_on": "START_OF_TARGET_NEXT_TURN"})
    elif choice == "speed":
        rows.append({"type": "speed", "applies_to": "target", "becomes": 0, "expires_on": "START_OF_TARGET_NEXT_TURN"})
    from dataclasses import replace
    # This damage already belongs to the confirmed hit, including a lethal
    # primary packet. Other riders keep their ordinary recipient legality.
    te.run_effects(replace(sub, continue_after_defeat=True), rows[:1])
    te.run_effects(sub, rows[1:])
    if choice == "save" and target.active:
        features = {str((a.parameters.get("typed") or {}).get("source") or ""): a.display_name
                    for a in engine.action_catalog.values() if a.owner_id == actor.entity_id
                    and str((a.parameters.get("typed") or {}).get("source") or "").startswith(("tianxia.subpath.body.", "tianxia.path.body_refining"))}
        features.update({str(row['feature_id']): str(row['name'])
                         for row in engine.typed_passive_rows.get(actor.entity_id, [])
                         if str(row.get('feature_id', '')).startswith(('tianxia.subpath.body.', 'tianxia.path.body_refining'))
                         and row.get('name')})
        for action in engine.action_catalog.values():
            if action.owner_id == actor.entity_id:
                features.update(action.parameters.get('adaptation_body_features') or {})
        feature = ask(engine, ctx.intent, checkpoint_id(engine, "lesson_feature", target.entity_id), actor,
                      "choice:needle.lesson_feature", sorted(features), labels=features,
                      prompt=f"Return the Lesson: name your Body Refining feature for {target.display_name}'s next saving throw.")
        if not feature:
            return
        engine._apply_condition(target, LESSON_SAVE, PREFIX + "return_the_lesson", actor.entity_id,
                                expires_on=f"END_OF_SOURCE_TURN_AT:{int(actor.turns_started) + 1}",
                                data={"feature": feature[0], "label": f"Disadvantage on its next save against {features[feature[0]]}"})
    elif choice == "move":
        from .rider_movement import routes, step

        paths = routes(engine, actor, 10)
        if paths:
            where = ask(engine, ctx.intent, checkpoint_id(engine, "return_lesson_move", actor.entity_id), actor, "choice:needle.return_lesson_move",
                        sorted(paths), allow_decline=True, labels={k: "Move to " + k.removeprefix("cell:") for k in paths},
                        prompt=f"Return the Lesson: {actor.display_name} may move up to 10 feet without provoking.", target_id=actor.entity_id)
            if where and where[0] in paths:
                step(engine, actor, paths[where[0]], PREFIX + "return_the_lesson")


@hook("save")
def lesson_save(ctx: Any, subject: Any, ability: str, named: Any) -> dict[str, Any] | None:
    if not feature_available(ctx.engine, ctx.actor, 'lesson'):
        return None
    held = next((c for c in subject.conditions.values() if c.condition_id == LESSON_SAVE and c.source_actor_id == ctx.actor.entity_id), None) \
        if subject is not None else None
    source = str(ctx.typed.get("source") or ctx.source)
    if held is None or source != held.data.get("feature"):
        return None
    subject.conditions.pop(held.instance_id)
    ctx.engine._append_event("CONDITION_REMOVED", held.source_definition_id, actor_id=ctx.actor.entity_id, target_ids=(subject.entity_id,),
                             payload={"condition_id": LESSON_SAVE, "instance_id": held.instance_id, "reason": "CONSUMED"})
    return {"bonus": 0, "modes": ["DISADVANTAGE"]}
