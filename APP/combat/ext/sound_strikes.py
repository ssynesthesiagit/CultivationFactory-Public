"""Owned Sound BASE checks, source-zone consumers and two paid melee modifiers.

Body Resonance Strike and Thunder-Meridian Strike trigger on melee weapon attacks
or Unarmed Strikes, not Resonant Note's ranged Cultivation Attack. The authority
names Unarmed Strike for the compiler's existing core modifier pass. This hook
offers the same optional variants on the character's actual melee weapons, with
one action per printed outcome and payment. Ranged/thrown deliveries are excluded.
No saved-fight engine file changes are needed.
"""

import copy
from typing import Any

from . import effect, hook

FEATURES = ("TAL_SOUND_BODY_RESONANCE_STRIKE", "TAL_SOUND_THUNDER_MERIDIAN_STRIKE")
NOTE = 'TAL_SOUND_RESONANT_NOTE'
HIDING = 'condition:typed.sound_hiding_block'


@hook('compile_actions')
def ordinary_hiding_option(info):
    """Extend the existing Note menu, preserving all other owners' damage/riders."""
    if NOTE not in info['owned_ids']:
        return None
    # Clone its existing base attack, not a second implementation of its damage.
    base = next((a for a in info['actions'] if ((a.parameters or {}).get('typed') or {}).get('source') == NOTE
                 and not (((a.parameters or {}).get('typed') or {}).get('variant'))), None)
    if base is None:
        base = next((a for a in info['actions'] if ((a.parameters or {}).get('typed') or {}).get('source') == NOTE), None)
    if base is None:
        return None
    typed = copy.deepcopy(base.parameters['typed'])
    attack = next((row for row in typed['effects'] if row.get('type') == 'attack'), None)
    if attack is None:
        return None
    attack['on_hit'] = [row for row in attack.get('on_hit', []) if row.get('type') != 'if_marked']
    attack['on_hit'].insert(0, {'type': 'if_marked', 'mark': 'Resonance', 'at': 'hit', 'applies_to': 'target',
        'effects': [{'type': 'sound_hiding_block', 'duration': {'kind': 'until_start_of_your_next_turn'}}]})
    typed['riders'] = []
    typed['option_label'] = 'Prevent ordinary sound-based hiding'
    return [base.model_copy(update={'source_definition_id': base.source_definition_id + '#ordinary_sound_hiding',
        'display_name': 'Resonant Note: Prevent ordinary sound-based hiding',
        'parameters': {**base.parameters, 'typed': typed}})]


@hook('compile_actions')
def vibration_choices(info):
    """Declare the existing action's inline owner choices to the table service."""
    for action in info['actions']:
        typed = (action.parameters or {}).get('typed') or {}
        if typed.get('source') == 'TAL_SOUND_READ_THE_VIBRATION':
            typed['manual_inline_choice'] = True
            typed['gm_adjudication'] = True
    return None


@hook('technique_start')
def sound_scene_receipts(engine, source, action):
    """Record hearing at delivery time, not from a later roster/geometry snapshot."""
    from .. import speech
    from ..typed_executor import condition_rules
    if not speech.needs_voice(action) or speech.silenced(source):
        return
    listeners = [actor.entity_id for actor in engine.state.actors.values() if actor.active
                 and engine._distance_actor_to_actor(actor, source) <= 60
                 and not any(r.get('cant_hear') for r in condition_rules(actor))
                 and speech.can_hear_from(engine, source, actor, action.source_definition_id)
                 and engine.grid.line_of_sight_between_cell_sets(engine._actor_volume(actor), engine._actor_volume(source))
                 and any(((engine.action_catalog[aid].parameters or {}).get('typed') or {}).get('source') == 'TAL_SOUND_READ_THE_VIBRATION'
                         for aid in actor.action_ids if aid in engine.action_catalog)]
    for listener in listeners:
        engine._append_event('PASSIVE_TRIGGERED', action.source_definition_id, actor_id=listener,
            target_ids=(listener,), payload={'sound_scene_receipt': 1, 'hidden_source': int(unseen_source(source)),
                'source_actor_id': source.entity_id, 'source_turn': source.turns_started,
                'listener_turn': engine.state.actors[listener].turns_started,
                'round_number': engine.state.round_number,
                'source_position': source.position.model_dump(mode='json'),
                'supernatural_influence': int(bool((action.parameters or {}).get('sensory_facts', {}).get('supernatural_influence'))),
                'trigger': 'Audible voice', 'text': 'A voice produced a vibration within hearing range.'})


def unseen_source(source):
    """Hidden/Invisible status only, without granting an observer sight or identity."""
    return any(c.condition_id in ('condition:typed.hidden', 'condition:typed.invisible')
               for c in source.conditions.values())


def recent_sound_receipts(engine, listener):
    """Bounded historical hearing provenance, not a claim of continuous speech.

    Sound Read's contests and clues share these primitive journal receipts.
    A receipt is usable through the listener's next turn only, and only while
    its living, unsilenced source remains within range on an audible path.
    Old receipts without provenance cannot establish scene facts. Source IDs
    and positions are internal evidence; unseen source choices use event tokens.
    """
    from .. import speech
    for event in reversed(engine.events):
        data = event.payload
        if not data.get('sound_scene_receipt') or listener.entity_id not in event.target_ids:
            continue
        heard_turn = data.get('listener_turn')
        if type(heard_turn) is not int or not 0 <= listener.turns_started - heard_turn <= 1:
            continue
        source = engine.state.actors.get(data.get('source_actor_id'))
        if source is None or not source.active or source.current_hp <= 0 or speech.silenced(source):
            continue
        if engine._distance_actor_to_actor(listener, source) > 60:
            continue
        if not speech.can_hear_from(engine, source, listener, event.source_definition_id):
            continue
        if not engine.grid.line_of_sight_between_cell_sets(engine._actor_volume(listener), engine._actor_volume(source)):
            continue
        yield event, source


@effect('sound_hiding_block')
def sound_hiding_block(ctx, eff):
    if ctx.target is None or ctx.typed.get('source') != NOTE:
        return
    ctx.engine._apply_condition(ctx.target, HIDING, ctx.source, ctx.actor.entity_id,
        expires_on='START_OF_MARKER_NEXT_TURN',
        data={'marker_turn': ctx.actor.turns_started,
              'label': 'Cannot hide by ordinary sound',
              'reading': 'Until the caster starts their next turn, this creature cannot hide its ordinary sounds from a listener who can hear it. This does not grant sight, exact location or the ability to hear through a solid barrier.'})


def ordinary_sound_hiding_blocked(engine, source, observer):
    """An audible ordinary source cannot hide its sound; never grants sight/location."""
    from .. import speech
    from ..typed_executor import condition_rules
    # Note's 60-foot range limits its attack, not who can hear the marked target.
    if source is None or observer is None:
        return False
    if any(row.get('cant_hear') for row in condition_rules(observer)):
        return False
    if not speech.can_hear_from(engine, source, observer, NOTE):
        return False
    if not engine.grid.line_of_sight_between_cell_sets(engine._actor_volume(observer), engine._actor_volume(source)):
        return False
    return any(c.condition_id == HIDING for c in source.conditions.values())


@hook('check_success_allowed')
def cannot_hide_ordinary_sound(ctx, subject, spec, roll):
    metadata = ctx.check_metadata
    if metadata.get('purpose') != 'conceal_sound' or metadata.get('senses') != ['hearing'] or metadata.get('ordinary') != 1:
        return None
    if metadata.get('source_actor_id') != subject.entity_id:
        return None
    observer = ctx.engine.state.actors.get(metadata.get('observer_id'))
    return False if ordinary_sound_hiding_blocked(ctx.engine, subject, observer) else None


@effect('sound_read_vibration')
def read_vibration(ctx, eff):
    """Bind an inquiry to its contest before rolling for one bounded clue.

    GM difficulty is entered transactionally, never invented by an AI. Scene
    facts are separate from rolling: only native movement/voice receipts or
    explicitly recorded object sensory_facts answer a question. Missing facts
    stay unknown. Neither this action nor Note removes Hidden or grants sight.
    """
    from .needle import ask, checkpoint_id
    from ..senses import perceives
    from ..typed_executor import resolve_opposed_check
    from .scoped_checks import select_gm_dc
    owner = ctx.actor
    topics = {'movement': 'Recent movement through a nearby space', 'structure': 'Hollow, cracked, tensioned, sealed or reinforced structure',
              'hidden_sound': 'Meaningful sound from an invisible or hidden creature', 'object': 'Resonant, brittle or sound-warded object',
              'influence': 'Supernatural influence in a phrase, bell, song or chant'}
    picked = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, 'vibration_clue', ctx.source), owner,
        'choice:needle.vibration_clue', list(topics), name='Read the Vibration', labels=topics,
        prompt='Read the Vibration: choose one inquiry before rolling. This costs your action and no cultivation points. '
            'A creature contest concerns only that creature; scene or object facts require a GM-set difficulty. '
            'Success provides one clue, without exact locations or sight through walls.')
    if not picked:
        return
    topic = picked[0]
    opponents = {a.entity_id: a for a in ctx.engine.state.actors.values() if a.active and a.entity_id != owner.entity_id
                 and ctx.engine._distance_actor_to_actor(owner, a) <= 60 and perceives(ctx.engine, owner, a)}
    labels = {key: actor.display_name for key, actor in opponents.items()}
    seen_sources = {a.entity_id for a in opponents.values()}
    for event, source in recent_sound_receipts(ctx.engine, owner):
        if source.entity_id == owner.entity_id or source.entity_id in seen_sources:
            continue
        token = 'sound:' + str(event.sequence)
        opponents[token] = source
        labels[token] = 'Unseen audible source ' + str(sum(k.startswith('sound:') for k in opponents))
        seen_sources.add(source.entity_id)
    methods = {'stealth': {'kind': 'check', 'ability': 'DEX', 'skill': 'Stealth', 'label': 'Dexterity (Stealth)'},
               'sleight': {'kind': 'check', 'ability': 'DEX', 'skill': 'Sleight of Hand', 'label': 'Dexterity (Sleight of Hand)'},
               'perception': {'kind': 'check', 'ability': 'WIS', 'skill': 'Perception', 'label': 'Wisdom (Perception)'},
               'cultivation': {'kind': 'cultivation', 'label': 'Cultivation concealment check'}}
    scene_inquiry = topic in ('structure', 'object')
    method = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, 'vibration_method', ctx.source), owner,
        'choice:needle.vibration_method', ['gm_dc'] if scene_inquiry else ['gm_dc', *methods], name='Read the Vibration',
        preferred=['stealth'] if opponents and not scene_inquiry else ['gm_dc'], labels={'gm_dc': 'Enter the difficulty set by the GM',
            **{k: 'Opposed by ' + v['label'] for k, v in methods.items()}},
        prompt='Read the Vibration: choose the GM-set difficulty for scene or object facts, or a relevant opposing check '
            'for one creature\'s movement, sound or supernatural influence. A creature contest reveals nothing about other sources.')
    if not method:
        return
    if method[0] == 'gm_dc':
        dc = select_gm_dc(ctx, 'Read the Vibration')
        if dc is None:
            return
        target, resistance = owner, {'kind': 'dc', 'dc': dc, 'label': 'GM-set difficulty'}
    else:
        ids = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, 'vibration_opponent', ctx.source), owner,
            'choice:needle.vibration_opponent', list(opponents), name='Read the Vibration',
            labels=labels,
            prompt='Read the Vibration: choose a perceived creature or an unseen source you recently heard within 60 feet. '
                'Only this creature can supply the chosen clue. An unseen source reveals no identity or exact location.')
        if not ids:
            return
        target = opponents[ids[0]]
        resistance = dict(methods[method[0]])
        resistance['metadata'] = {'source_actor_id': target.entity_id, 'observer_id': owner.entity_id,
                                  'senses': ['hearing'], 'purpose': 'conceal_sound',
                                  'ordinary': int(method[0] in ('stealth', 'sleight'))}
    metadata = {'source_actor_id': target.entity_id, 'observer_id': owner.entity_id, 'senses': ['hearing'],
                'purpose': 'read_vibration', 'method': method[0], 'inquiry': topic}
    if method[0] != 'gm_dc' and ids[0].startswith('sound:'):
        metadata['opponent_display_name'] = labels[ids[0]]
    result = resolve_opposed_check(ctx, target, {'kind': 'cultivation', 'label': 'Sound Check', 'metadata': metadata}, resistance)
    if not result.success:
        return
    # An opposed success only answers this creature's inquiry. Unrelated scene
    # evidence remains reachable through the GM route, never a weaker opponent.
    inquiry_source = None if method[0] == 'gm_dc' else target.entity_id
    # A boolean clue from the committed scene, never a coordinate/name dump.
    witnessed = []
    if topic == 'movement':
        # A round is six seconds. Current/previous-round evidence is recent;
        # journaled ROUND_STARTED boundaries survive commit/reload and avoid
        # assigning an age to movement records with no temporal provenance.
        recorded_round = None
        for event in ctx.engine.events:
            if event.event_type == 'ROUND_STARTED':
                recorded_round = event.payload.get('round')
            at = event.payload.get('destination') if event.event_type == 'MOVEMENT_COMMITTED' else None
            if (at and (inquiry_source is None or event.actor_id == inquiry_source)
                    and type(recorded_round) is int
                    and 0 <= ctx.engine.state.round_number - recorded_round <= 1
                    and ctx.engine.grid.distance_between_cell_sets_ft(ctx.engine._actor_volume(owner), [(at['x'], at['y'], at.get('z', 0))]) <= 60):
                witnessed.append(event.sequence)
        if witnessed:
            clue = 'Vibration records movement through a nearby space in this round or the previous round.'
        elif inquiry_source is not None:
            clue = 'No recent movement by the chosen creature is recorded nearby; unrecorded movement remains unknown.'
        else:
            clue = 'No recent movement is recorded in the nearby scene; unrecorded movement remains unknown.'
    elif topic in ('hidden_sound', 'influence'):
        key = 'hidden_source' if topic == 'hidden_sound' else 'supernatural_influence'
        witnessed = [e.sequence for e, source in recent_sound_receipts(ctx.engine, owner)
                     if (inquiry_source is None or source.entity_id == inquiry_source)
                     and e.payload.get(key) and (topic != 'hidden_sound' or unseen_source(source))]
        clue = ('A hidden or invisible source produced meaningful sound since your previous turn; '
                'this is recent evidence, and whether it is still making sound is unknown.' if topic == 'hidden_sound'
                else 'A phrase, bell, song or chant heard since your previous turn is recorded as carrying supernatural influence.') if witnessed else (
                'No qualifying sound is recorded' + (' for the chosen creature' if inquiry_source is not None else '')
                + '; unrecorded sounds or influence remain unknown.')
    elif topic in ('structure', 'object'):
        keys = ('hollow', 'cracked', 'tensioned', 'sealed', 'reinforced') if topic == 'structure' else ('resonant', 'brittle', 'warded_against_sound')
        facts = [(obj, key) for obj in ctx.engine.state.objects.values() for key in keys
                 if (obj.component or {}).get('sensory_facts', {}).get(key) == 1
                 and ctx.engine.grid.distance_between_cell_sets_ft(ctx.engine._actor_volume(owner), [(obj.position.x, obj.position.y, obj.position.z)]) <= 60
                 and ctx.engine.grid.line_of_sight_between_cell_sets(ctx.engine._actor_volume(owner), [(obj.position.x, obj.position.y, obj.position.z)])]
        clue = 'A nearby structure is recorded as ' + facts[0][1].replace('_', ' ') + '.' if facts else (
            'The scene has no recorded physical evidence for that clue; the fact remains unknown.')
    else:
        # Narrative properties cannot be inferred from AC, HP, display names,
        # roster membership or success on a die. Keep these printed choices
        # available, while disclosing absent scene evidence precisely.
        clue = 'The scene has no recorded evidence for that clue; the physical or supernatural fact remains unknown.'
    ctx.engine._append_event('PASSIVE_TRIGGERED', ctx.source, actor_id=owner.entity_id, target_ids=(),
        payload={'trigger': 'Read the Vibration', 'text': clue, 'clue': topic, 'check_roll_id': result.actor.roll_id,
                 'observer_id': owner.entity_id, 'evidence_sequences': witnessed, 'exact_location': 0})


def dampening_zones(engine):
    """Only live, paid Dampen Sound zones; no label-based inferred ownership."""
    from ..zones import typed_zones
    for zone in typed_zones(engine):
        source = engine.action_catalog.get(zone.source_definition_id)
        owner = engine.state.actors.get(zone.owner_id)
        owned = owner is not None and source is not None and zone.source_definition_id in owner.action_ids
        if (owned and ((source.parameters or {}).get('typed') or {}).get('source') == 'TAL_SOUND_DAMPEN_SOUND'
                and any(row.get('rule', {}).get('sound_dampening') for row in zone.trigger_profile.get('inside', []))):
            yield zone


@hook('scene_check_relevant')
def dampening_scene_check(engine, actor, purpose):
    """Owners and a live dampened scene expose the quiet-movement check.

    A live zone can affect listeners outside it too. Keep the check reachable
    throughout that scene; actual Advantage still requires the mover inside.
    Nonowners without a live zone leave ordinary action menus unchanged.
    """
    if purpose == 'notice_sound':
        # A creature outside at least one live zone can hear sources inside that
        # zone, even while it stands inside another one (per-zone, as dampening_mode).
        from ..spatial_areas import zone_contains
        return True if any(not zone_contains(engine, actor, zone) for zone in dampening_zones(engine)) else None
    if purpose != 'quiet_movement':
        return None
    owned = any(((action.parameters or {}).get('typed') or {}).get('source') == 'TAL_SOUND_DAMPEN_SOUND'
                for source in actor.action_ids if (action := engine.action_catalog.get(source)) is not None)
    return True if owned or any(dampening_zones(engine)) else None


@hook('compile_actions')
def listen_for_dampened_sound(info):
    """Production route for the outside hearing-only Perception consumer.

    Any creature may choose this ordinary check while a live dampening zone exists
    and it stands outside. Dormant otherwise (scoped_checks.relevant_scene_check).
    Source and DC come from explicit choices; the check carries source geometry
    and hearing facts that dampening_mode consumes. No free roll or invented DC.
    """
    from ..gate2_runtime_models import ActionDefinition, EconomyKind
    return [ActionDefinition(
        source_definition_id=f"action:typed.{info['short']}.listen_dampened",
        display_name='Listen for sound inside a dampened zone', owner_id=info['actor_id'],
        economy=EconomyKind.NONE, resolution_kind='TYPED', target_kind='SELF',
        parameters={'typed': {'effects': [{'type': 'sound_listen_check'}],
                    'numbers': info['numbers'], 'duration': {'kind': 'instant'},
                    'manual_inline_choice': True, 'gm_adjudication': True}, 'expected_damage': 0,
                    'scene_check_purpose': 'notice_sound',
                    'description': 'Roll Wisdom (Perception) to notice sound from a creature inside a dampened zone. '
                        'Only sound counts: sight is not a source here, and this check does not move you.'})]


@effect('sound_listen_check')
def listen_check(ctx, eff):
    """Choose an inside creature by opaque position label, then enter the GM DC."""
    from ..spatial_areas import zone_contains
    from ..typed_executor import resolve_opposed_check
    from .needle import ask, checkpoint_id
    from .scoped_checks import select_gm_dc
    from .. import speech
    zones = list(dampening_zones(ctx.engine))
    if not zones:
        return
    # A listener outside at least one zone can hear sources in that zone,
    # even if they occupy a different live zone. Evaluate each source-zone pair.
    audible_zones = [zone for zone in zones if not zone_contains(ctx.engine, ctx.actor, zone)]
    # Only sources this listener can hear: Deafened (cant_hear) and sound-path vetoes apply here too,
    # through the same hearing predicate every other recipient route uses.
    inside = sorted((a for a in ctx.engine.state.actors.values() if a.active and a.entity_id != ctx.actor.entity_id
                     and any(zone_contains(ctx.engine, a, zone) for zone in audible_zones)
                     and speech.can_hear_from(ctx.engine, a, ctx.actor, ctx.source)), key=lambda a: a.entity_id)
    if not inside:
        return
    # Labels stay generic: no identity, exact location or sight is disclosed.
    labels = {a.entity_id: 'Creature inside the dampened zone ' + str(i + 1) for i, a in enumerate(inside)}
    # The table answers which creature is heard, even on an automatic seat (no AI guess at a scene fact).
    picked = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, 'listen_source', ctx.source), ctx.actor,
        'choice:needle.listen_source', [a.entity_id for a in inside], name='Listen for sound inside a dampened zone',
        automatic=False, allow_decline=True, default='decline', labels=labels, gm_adjudication=True,
        prompt='Listen for sound inside a dampened zone: choose the creature inside whose sound you try to notice. '
            'Only hearing counts; this costs no cultivation points and does not move you.')
    if not picked:
        return
    dc = select_gm_dc(ctx, 'Listen for sound inside a dampened zone')
    if dc is None:
        return
    metadata = {'purpose': 'notice_sound', 'senses': ['hearing'], 'source_actor_id': picked[0],
                'observer_id': ctx.actor.entity_id}
    resolve_opposed_check(ctx, ctx.actor,
        {'kind': 'check', 'ability': 'WIS', 'skill': 'Perception', 'metadata': metadata},
        {'kind': 'dc', 'dc': dc, 'label': 'GM-set difficulty'})


def dampening_mode(engine, subject, ability, skill, metadata):
    """Current source/observer geometry; absent or mixed sensory context is inert.

    One containment rule for the whole plug-in: a creature is inside a zone when
    zone_contains says so (the same rule the Listen source list and the
    outside-listener gate use). A straddling source therefore counts as inside,
    exactly as it is offered in the Listen choice.
    """
    from ..spatial_areas import zone_contains, zone_contains_cells
    if not metadata:
        return None
    if metadata.get('purpose') == 'quiet_movement' and metadata.get('issues') == ['sound']:
        if any(zone_contains(engine, subject, zone) for zone in dampening_zones(engine)):
            return 'ADVANTAGE'
    if ability.upper() != 'WIS' or str(skill).casefold() != 'perception' or metadata.get('senses') != ['hearing']:
        return None
    if metadata.get('observer_id') != subject.entity_id:
        return None
    source = engine.state.actors.get(metadata.get('source_actor_id'))
    point = metadata.get('source_position')
    if source is not None:
        def source_inside(zone):
            return zone_contains(engine, source, zone)
    elif isinstance(point, dict):
        cell = [(point['x'], point['y'], point.get('z', 0))]

        def source_inside(zone):
            return zone_contains_cells(engine, cell, zone)
    else:
        return None
    if any(not zone_contains(engine, subject, zone) and source_inside(zone) for zone in dampening_zones(engine)):
        return 'DISADVANTAGE'
    return None


@hook('ability_check_mode')
def dampened_ability_check(engine, actor, ability, skill, against):
    from ..check_context import current
    return dampening_mode(engine, actor, ability, skill, current(engine, actor))


@hook('skill_check_mode')
def dampened_skill_check(ctx, subject, ability, skill):
    return dampening_mode(ctx.engine, subject, ability, skill, ctx.check_metadata)


@hook('final_damage')
def dampened_thunder(engine, target, amount, damage_type, source_id, source_actor_id, intent):
    if damage_type.upper() != 'THUNDER' or amount <= 0:
        return None
    zones = list(dampening_zones(engine))
    if not zones:
        return None
    from ..save_context import damage_geometry
    from ..spatial_areas import zone_contains_cells, zone_volume_inside
    geometry = damage_geometry(engine, target.entity_id, source_id, source_actor_id)
    if geometry is None:
        return None
    cells = geometry['source_cells'] + geometry['recipient_cells'] + geometry['area_cells']
    from ..zones import typed_zones
    source_region = next((z for z in typed_zones(engine) if z.zone_id == geometry.get('source_zone_id')), None)
    reductions = [int(engine.state.actors[zone.owner_id].proficiency_bonus) for zone in zones
                  if cells and all(zone_contains_cells(engine, [cell], zone) for cell in cells)
                  and (not geometry.get('source_zone_id') or source_region is not None
                       and zone_volume_inside(engine, source_region, zone))]
    return {'reduction': min(amount, max(reductions))} if reductions else None


@effect("sound_equipped_resonance")
def equipped_resonance(ctx: Any, eff: dict[str, Any]) -> None:
    """Body Resonance's equipment predicate, using the evented carry/disarm state.

    Only the new paid modifier row opts in. Worn body armor, carried shields, own
    held weapons and taken weapons count. Spare unworn armor and dropped/disarmed
    equipment do not. "Or is a construct": a creature labelled Construct (the
    shared classification, combat/ext/creature_kinds.py; rider lane C12) -- AC or
    immunity is no proxy, and an unlabelled creature is not one.
    """
    from .. import carry
    from ..typed_executor import block_mark

    identities = str((ctx.typed.get("modifier") or {}).get("id") or "").split("+")
    if FEATURES[0] not in identities and ctx.effect_source != FEATURES[0]:
        return
    target = ctx.target
    if target is None or not target.active:
        return
    items = (carry.carrying_of(ctx.engine, target.entity_id) or {}).get("items") or []
    equipped = any((item.get("worn") or item.get("weapon_action")
                    or item.get("item_id") == "tianxia.mortal.armor.shield")
                   and carry.holds(ctx.engine, target, item["key"]) for item in items)
    # Taken weapons stay in their original owner's evented Disarmed condition.
    equipped = equipped or any((c.data or {}).get("held_by") == target.entity_id
                              and (c.data or {}).get("disables_action")
                              for owner in ctx.engine.state.actors.values() for c in owner.conditions.values())
    if not equipped:
        from .creature_kinds import matches

        equipped = matches(target, ["construct"])
    if equipped:
        block_mark(ctx, {**eff, "type": "mark", "mark": "Resonance", "applies_to": "target",
                         "duration": {"kind": "until_start_of_your_next_turn"}})


@hook("effect_description")
def resonance_description(row: dict[str, Any]) -> str | None:
    """Explain Sound's named mark in both its ordinary and equipment-gated rows."""
    if row.get('type') == 'sound_hiding_block':
        return ('A target already bearing your Resonance mark cannot hide its ordinary sounds from a listener '
                'who can hear it until the start of your next turn. This does not grant sight or exact location.')
    if row.get('type') == 'sound_read_vibration':
        return ('Use one Action, no cultivation points, to make a Sound Check against the GM’s difficulty or a relevant '
                'opposing Dexterity (Stealth), Dexterity (Sleight of Hand), Wisdom (Perception), or cultivation '
                'concealment check. Success yields one clue about vibration within 60 feet. Unrecorded scene facts '
                'remain unknown. This never automatically reveals exact locations, grants sight through walls or '
                'identifies every creature.')
    if row.get("type") == "sound_equipped_resonance" or (row.get("type") == "mark" and row.get("mark") == "Resonance"):
        return ("Resonance: a mark from you on the target. Your Sound talents can gain extra effects against a target "
                "bearing your mark; for example, Resonant Note can deafen it on a later hit. "
                "The mark lasts for the duration stated in the effect.")
    return None


@hook("compile_actions")
def melee_strikes(info: dict[str, Any]) -> list[Any] | None:
    from ..factory_compiler import RESOURCE_IDS, _attach

    melee = {w["action_id"] for w in info.get("weapon_kinds") or [] if w.get("melee")}
    result = []
    for feature in FEATURES:
        if feature not in info["owned_ids"]:
            continue
        mechanic = info["mechanics"][feature]
        modifier = mechanic.get("modifier") or {}
        for action in info["actions"]:
            if action.source_definition_id not in melee:
                continue
            typed = (action.parameters or {}).get("typed") or {}
            for index, option in enumerate(modifier.get("options") or [{}]):
                effects = copy.deepcopy([{**row, "source_modifier": feature}
                                         for row in [*(modifier.get("effects") or []), *(option.get("effects") or [])]])
                payments = set()
                for way, payment in enumerate(modifier.get("cost") or [[]]):
                    # CP maps to the primary Path pool. Keep only held pools and
                    # one row when two printed ways resolve to the same payment.
                    resolved = [(info["primary"] if c["resource"] == "cp" else c["resource"], int(c["amount"]))
                                for c in payment]
                    if any(name not in info.get("pools", (info["primary"],)) for name, _amount in resolved):
                        continue
                    signature = tuple(sorted(resolved))
                    if signature in payments:
                        continue
                    payments.add(signature)
                    costs = list(action.costs)
                    label = ""
                    for cost in payment:
                        name = cost["resource"]
                        resource = RESOURCE_IDS[info["primary"]] if name == "cp" else RESOURCE_IDS[name]
                        costs.append((resource, int(cost["amount"])))
                        label = f" ({cost['amount']} {name.upper()})"
                    suffix = f": {option['label']}" if option.get("label") else ""
                    updated = {**typed, "numbers": {**(typed.get("numbers") or {}), "save_dc": info['numbers']['save_dc']},
                               "effects": _attach(typed.get("effects") or [], effects, "hit"),
                               "modifier": {"id": feature, "name": mechanic["name"]}}
                    result.append(action.model_copy(update={
                        "source_definition_id": f"{action.source_definition_id}#sound.{feature}.{index}.{way}",
                        "display_name": f"{action.display_name} + {mechanic['name']}{suffix}{label}",
                        "costs": tuple(costs), "parameters": {**action.parameters, "typed": updated}}))
    return result or None
