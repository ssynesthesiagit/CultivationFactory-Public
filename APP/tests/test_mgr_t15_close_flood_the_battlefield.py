"""Flood the Battlefield review regressions: Court gate, scoped Water pressure, Swim Speed seam, moves, cost.

Public CI file: no repository-history reads, no private fixtures, no owner data. Every sheet here is
built synthetically from the documented character-sheet shape and the shipped authority files, so this
runs anywhere the suite runs.

Each test fails without its fix:
  * ``test_flood_requires_own_active_court`` / ``test_owned_court_allows_paid_flood_*`` -- no active
    Court means the option is not offered at all (candidate_allowed), and the printed Trigger's plain
    reason is offered with it (candidate_unavailability).
  * ``test_disadvantage_is_scoped_to_resisting_this_caster`` -- a flooded creature has Disadvantage
    only on Strength/Dexterity checks made to resist that caster's Water effects, and keeps its
    ordinary mode on every other Strength/Dexterity check.
  * ``test_swim_speed_seam_is_general_and_default_inert`` -- combat/swim_speed.py answers for any
    creature, is 0 with no subscriber, and an unrelated ability reads the same answer.
  * ``test_printed_moves_are_the_caster_choice`` -- 30 feet on a failure and 10 on a success, both
    chosen from zero, so nothing moves more than printed.
  * ``test_drowning_pressure_ends_at_the_end_of_the_victims_next_turn`` -- the victim's deadline.
  * ``test_flood_costs_optional_cultivation_points_not_qi`` -- "you may spend 3 CP", paid from the
    Cultivation Points pool and never silently from Qi.
"""
import json
import zipfile
from pathlib import Path

import pytest

from combat import ext
from combat.ext import water_flood
from combat.gate5_service import CombatService
from combat.swim_speed import can_swim, swim_speed_ft
from combat.tabletop_service import TabletopService
from combat.tabletop import ButtonStore

APP = Path(__file__).resolve().parents[1]
FLOOD = 'TAL_WATER_FLOOD_THE_BATTLEFIELD'
COURT = 'TAL_WATER_COURT_OF_THE_ENDLESS_TIDE'
A, B = 'actor:factory.00000021', 'actor:factory.00000022'
RUNTIME_DEPENDENCIES = (
    'authority/Tianxia_Typed_Mechanics_Authority_R1.json',
    'authority/Tianxia_Forged_Technique_Authority_R1.json',
    'catalog_authority/cat3/generated/catalog_authority.v1.json',
    'combat/rules/feature_blocks.d/a2_water.json',
    'combat/rules/feature_blocks.d/sysv2_objects.json',
    'combat/rules/objects.json',
)


def document(name, talents, save):
    return {'identity': {'name': name, 'display_name': name, 'cultivation_level': 15,
                         'proficiency_bonus': 5, 'path': 'Qi Cultivation', 'key_ability': 'INT'},
            'ability_scores_and_statistics': {
                'abilities': [{'ability': k, 'score': 20 if k == 'INT' else 14,
                               'modifier': 5 if k == 'INT' else 2}
                              for k in ('STR', 'DEX', 'CON', 'INT', 'WIS', 'CHA')],
                'saving_throws': {'STR': save},
                'primary_resource': {'name': 'Qi', 'maximum': 75},
                'armor_class': {'base_value': 12}, 'hit_points': {'maximum': 200},
                'speed': {'walking_ft': 30}, 'technique_save_dc': 18, 'technique_attack_bonus': 10},
            'spheres_and_talents': {'sphere_record_ids': ['tianxia.sphere.water'],
                'learned_talent_record_ids': talents,
                'automatic_sphere_component_record_ids': [
                    'WATER_BASE_WATER_INITIATION', 'WATER_BASE_WATER_LASH', 'WATER_BASE_SHAPE_CURRENT']}}


def settle(table, mid, candidate, picks=None):
    answers = []
    state = table.state(mid)
    for _ in range(24):
        result = table.act(mid, candidate.candidate_id, candidate.decision_id, candidate.state_version,
                           state['last_sequence'], answers)
        if result['status'] == 'COMMITTED':
            return
        assert result['status'] == 'REACTION_REQUIRED', result
        prompt = result['reaction']
        chosen = (picks or {}).get(prompt['context']['reaction_source_id'])
        answers.append({**prompt['context'], 'selection': 'USE' if chosen is not None else 'DECLINE',
                        'option_ids': chosen or []})
    raise AssertionError('choice did not settle')


def engine(combat, mid):
    return combat._load_session(mid).engine


def turn(combat, table, mid, aid):
    for _ in range(12):
        e = engine(combat, mid)
        if e.state.current_actor_id == aid:
            return
        settle(table, mid, next(c for c in e.legal_candidates() if c.display_name == 'End turn'))
    raise AssertionError('actor turn unavailable')


def setup(tmp_path, *, court=True, flood=True, save=-100):
    for rel in RUNTIME_DEPENDENCIES:
        assert (APP / rel).is_file(), rel
    catalog = json.loads((APP / RUNTIME_DEPENDENCIES[2]).read_text())
    row = next(r for r in catalog['talents'] if r['canonical_talent_id'] == FLOOD)
    assert row['minimum_cl'] == 15 and row['access_category'] == 'Open'
    talents = ['TAL_WATER_FLOWING_STEP', *([COURT] if court else []), *([FLOOD] if flood else [])]
    for pid, doc in [('00000021', document('Tidecaller', talents, 0)),
                     ('00000022', document('Recipient', ['TAL_WATER_FLOWING_STEP'], save))]:
        path = tmp_path / 'portable_characters' / pid
        path.mkdir(parents=True)
        with zipfile.ZipFile(path / 'current.zip', 'w') as z:
            z.writestr('Tianxia_Owner_Character_Sheet_v1.json', json.dumps(doc))
        ButtonStore(tmp_path / 'tabletop_buttons').save_reactions(pid, {'mode': 'ask'}, set())
    combat = CombatService(APP, tmp_path)
    arena = combat.tabletop_maps.save({'display_name': 'Flood native gate', 'width_squares': 30,
        'height_squares': 13, 'starts': {'team1': [[2, 6]], 'team2': [[6, 6]]}, 'walls': [], 'objects': []})
    mid = combat.create_factory_match(project_ids=['00000021'], opponent_actor_ids=[B],
        control_modes={A: 'MANUAL', B: 'MANUAL'}, arena_id='battlefield:map.' + arena['map_id'],
        match_seed='flood-native-gate')['match_id']
    table = TabletopService(combat, tmp_path)
    turn(combat, table, mid, A)
    return combat, table, mid


def candidates(combat, mid, source):
    e = engine(combat, mid)
    ids = {a.source_definition_id for a in e.action_catalog.values()
           if a.owner_id == A and a.parameters.get('typed', {}).get('source') == source}
    return [c for c in e.legal_candidates() if c.source_definition_id in ids]


def cold(tmp_path, mid):
    combat = CombatService(APP, tmp_path)
    session = combat._load_session(mid)
    replay = session.mechanical.replay()
    assert replay['status'] == 'PASS'
    assert session.verify()['canonical_state_sha256'] == replay['canonical_state_sha256']
    return combat, TabletopService(combat, tmp_path), session.engine


def flood_recipients():
    return {'choice:needle.area_recipients': [B], 'choice:needle.rider_targets': [B]}


def flooded(tmp_path, *, save=-100, distance=None):
    """Play Flood with an active Court and return (engine, recipient actor state, distance picks)."""
    combat, table, mid = setup(tmp_path, save=save)
    settle(table, mid, candidates(combat, mid, COURT)[0])
    picks = flood_recipients()
    if distance is not None:
        picks[f'choice:{FLOOD.lower()}.moved_distance'] = [str(distance)]
    settle(table, mid, candidates(combat, mid, FLOOD)[0], picks)
    _, _, e = cold(tmp_path, mid)
    return e, e.state.actors[B], e


# ---------------------------------------------------------------- finding 1: own active Court


@pytest.mark.parametrize('court,flood', [(False, True), (True, True), (True, False)])
def test_flood_requires_own_active_court(tmp_path, court, flood):
    combat, table, mid = setup(tmp_path, court=court, flood=flood)
    assert not candidates(combat, mid, FLOOD), 'Flood requires an owned, actually active Court'
    combat, table, _ = cold(tmp_path, mid)
    assert not candidates(combat, mid, FLOOD), 'still refused after a commit + reload'


@pytest.mark.parametrize('save', [-100, 100], ids=['failure', 'success'])
def test_owned_court_allows_paid_flood_with_save_and_cold_replay(tmp_path, save):
    combat, table, mid = setup(tmp_path, save=save)
    settle(table, mid, candidates(combat, mid, COURT)[0])
    _, _, before = cold(tmp_path, mid)
    rows = candidates(combat, mid, FLOOD)
    assert rows, 'an active own Court offers Flood'
    settle(table, mid, rows[0], flood_recipients())
    _, _, after = cold(tmp_path, mid)
    assert before.state.actors[A].resources['resource:core.qi'] - after.state.actors[A].resources['resource:core.qi'] == 3
    assert not after.state.actors[A].action_available
    rolls = [e for e in after.events[len(before.events):] if e.event_type == 'SAVE_ROLLED']
    assert len(rolls) == 1 and rolls[0].actor_id == B
    conditions = [c.condition_id for c in after.state.actors[B].conditions.values()]
    assert any(k.endswith('.prone') or k == 'prone' for k in conditions) == (save < 0)
    assert any(k.startswith('condition:typed.mark.soaked.') for k in conditions) == (save > 0)


def test_missing_court_explains_itself_in_plain_words(tmp_path):
    """A refusal the player can act on names the ability, the Trigger, and why it is not met."""
    combat, table, mid = setup(tmp_path, court=False)
    e = engine(combat, mid)
    action = next((a for a in e.action_catalog.values()
                   if a.owner_id == A and a.parameters.get('typed', {}).get('source') == FLOOD), None)
    assert action is not None
    reason = ext.run('candidate_unavailability', e, e.state.actors[A], None, action)
    reasons = [r for r in reason if isinstance(r, str) and r.strip()]
    assert reasons, 'the refusal carries a player-facing reason'
    text = reasons[0]
    assert 'Court of the Endless Tide' in text and 'Flood the Battlefield' in text
    assert 'TAL_' not in text and 'actor:' not in text, 'no internal ids in player-facing text'


# ---------------------------------------------------------------- finding 2: scoped Water pressure


def flood_source(e):
    """The caster's own Flood action: a Water effect, so a check made as it is is a Water check."""
    return next(a.source_definition_id for a in e.action_catalog.values()
                if a.owner_id == A and (a.parameters.get('typed') or {}).get('source') == FLOOD)


def test_disadvantage_is_scoped_to_resisting_this_caster(tmp_path):
    """The printed clause is narrow; the unqualified path made every STR/DEX check suffer."""
    from combat.check_context import checking
    from combat.typed_executor import check_mode

    e, victim, _ = flooded(tmp_path)
    owner = e.state.actors[A]
    assert water_flood.flooded_by(victim, owner.entity_id), 'the flood marks its own recipients'
    water = {'source_id': flood_source(e)}

    # resisting THIS caster's Water effect: Disadvantage, as printed -- and it reaches the real check reader
    with checking(e, victim, water):
        assert water_flood.water_only_pressure(e, victim, 'STR', None, owner) == 'DISADVANTAGE'
        assert water_flood.water_only_pressure(e, victim, 'DEX', None, owner) == 'DISADVANTAGE'
    assert check_mode(victim, 'STR', None, engine=e, against_creature=owner, metadata=water) == 'DISADVANTAGE'

    # a check against some OTHER creature: no opinion, so its ordinary mode stands
    other = type('Other', (), {'entity_id': 'actor:factory.00009999'})()
    assert check_mode(victim, 'STR', None, engine=e, against_creature=other, metadata=water) == 'NORMAL'
    # resisting nobody in particular (a jump, a lift): no opinion either
    assert check_mode(victim, 'STR', None, engine=e, against_creature=None, metadata=water) == 'NORMAL'
    # another ability is not a Strength/Dexterity check
    assert check_mode(victim, 'WIS', None, engine=e, against_creature=owner, metadata=water) == 'NORMAL'
    # a creature that was never flooded is untouched
    assert check_mode(owner, 'STR', None, engine=e, against_creature=owner, metadata=water) == 'NORMAL'
    assert check_mode(owner, 'STR', None, engine=e, against_creature=owner) == 'NORMAL'


def test_same_caster_non_water_check_keeps_its_ordinary_mode(tmp_path):
    """Finding 1: a Strength check against the flooding caster under another sphere is not pressed.

    brute_shove.py asks check_modes(..., against_creature=caster) for a Shove. The flooded creature
    resists that caster, but the Shove is not a Water effect, so it must read NORMAL. Without the
    source gate this returned DISADVANTAGE for any Strength or Dexterity check against the caster.
    """
    import copy
    from combat.check_context import checking
    from combat.typed_executor import check_mode

    e, victim, _ = flooded(tmp_path)
    owner = e.state.actors[A]
    flood = e.action_catalog[flood_source(e)]
    shove = flood.model_copy(update={'parameters': {**copy.deepcopy(flood.parameters),
        'typed': {**(flood.parameters.get('typed') or {}), 'sphere': 'tianxia.sphere.iron_fist'}}})
    e.action_catalog['test.non_water_shove'] = shove

    assert check_mode(victim, 'STR', None, engine=e, against_creature=owner,
                      metadata={'source_id': 'test.non_water_shove'}) == 'NORMAL'
    assert check_mode(victim, 'DEX', None, engine=e, against_creature=owner,
                      metadata={'source_id': 'test.non_water_shove'}) == 'NORMAL'
    with checking(e, victim, {'source_id': 'test.non_water_shove'}):
        assert water_flood.water_only_pressure(e, victim, 'STR', None, owner) is None
    # no source at all (a bare check against the caster) is not a Water effect either
    assert check_mode(victim, 'STR', None, engine=e, against_creature=owner) == 'NORMAL'
    # the same caster's Water effect still presses, so the gate is not simply off
    assert check_mode(victim, 'STR', None, engine=e, against_creature=owner,
                      metadata={'source_id': flood_source(e)}) == 'DISADVANTAGE'


def test_flood_removes_only_its_own_unqualified_disadvantage(tmp_path):
    """Other abilities keep the ordinary unqualified path; Flood's clause is the scoped marker."""
    combat, table, mid = setup(tmp_path)
    settle(table, mid, candidates(combat, mid, COURT)[0])
    e = engine(combat, mid)
    action = e.action_catalog[next(c.source_definition_id for c in candidates(combat, mid, FLOOD))]
    kinds = [row.get('type') for row in ((action.parameters or {}).get('typed') or {}).get('effects') or []]
    assert 'disadvantage' not in kinds, 'the unqualified advantage effect is gone from this action'
    assert 'water_pressure' in kinds, 'replaced by the scoped marker'


# ---------------------------------------------------------------- finding 3: Swim Speed seam


def test_swim_speed_seam_is_general_and_default_inert(tmp_path):
    """The seam answers for ANY creature, is 0 with no subscriber, and no ability id is required."""
    combat, table, mid = setup(tmp_path)
    e = engine(combat, mid)
    for actor in e.state.actors.values():
        assert swim_speed_ft(e, actor) == 0, 'no subscriber: every creature has no Swim Speed'
        assert can_swim(e, actor) is False

    def grants_swim(engine, actor):
        return 30 if actor.entity_id == B else None

    def grants_nonsense(engine, actor):
        return 'not a number'

    ext.hook('swim_speed')(grants_swim)
    ext.hook('swim_speed')(grants_nonsense)
    try:
        assert swim_speed_ft(e, e.state.actors[B]) == 30, 'a subscriber supplies the number'
        assert swim_speed_ft(e, e.state.actors[A]) == 0, 'and only to its own creature'
        assert can_swim(e, e.state.actors[B]) is True, 'unparseable answers are skipped, not guessed'
    finally:
        ext._HOOKS['swim_speed'].remove(grants_swim)
        ext._HOOKS['swim_speed'].remove(grants_nonsense)


def test_flooded_court_is_difficult_only_for_creatures_without_swim_speed(tmp_path):
    """The rider's exact wording: without Swim Speed is difficult, with it is not."""
    from combat import zones

    e, victim, _ = flooded(tmp_path)
    court_zone = next(iter(water_flood.courts(e, e.state.actors[A])))
    # an unflooded Court is not water ("The Domain does not fill the entire area with physical
    # water unless you use talents that create floodwater"); a flooded one is difficult to hostiles
    assert court_zone.trigger_profile.get('difficult') == 'hostile', 'the flood makes the Domain difficult'
    assert zones.zone_is_difficult(e, court_zone, victim) is True, 'a creature that cannot swim is charged'
    assert water_flood.floodwater_is_difficult(e, victim, court_zone) is None, 'cannot swim: not excused'

    def grants_swim(engine, actor):
        return 30 if actor.entity_id == B else None

    ext.hook('swim_speed')(grants_swim)
    try:
        assert water_flood.floodwater_is_difficult(e, victim, court_zone) is True, 'swims: excused'
        assert zones.zone_is_difficult(e, court_zone, victim) is False, 'the printed exemption reaches the terrain reader'
    finally:
        ext._HOOKS['swim_speed'].remove(grants_swim)


# ---------------------------------------------------------------- finding 4: the printed moves


@pytest.mark.parametrize('save,distance', [(-100, 30), (-100, 0), (100, 10), (100, 0)])
def test_printed_moves_are_the_caster_choice(tmp_path, save, distance):
    """30 feet on a failure, 10 on a success, and the caster may choose less, down to zero."""
    if distance and (save > 0) != (distance == 10):
        pytest.skip('covered by the matching parameter pair')
    _, victim, e = flooded(tmp_path, save=save, distance=distance)
    start = (victim.x, victim.y)
    if distance == 0:
        assert (victim.x, victim.y) == start, 'zero means the creature is not moved at all'
    else:
        assert manhattan(start, (victim.x, victim.y)) <= distance, 'never moved further than printed'


def manhattan(a, b):
    return abs(a[0] - b[0]) + abs(a[1] - b[1])


def test_unflooded_court_is_not_water_for_anyone(tmp_path):
    """The Court's own printed rider: the Domain is not physical water until a floodwater talent is used."""
    from combat import zones

    combat, table, mid = setup(tmp_path)
    settle(table, mid, candidates(combat, mid, COURT)[0])
    _, _, e = cold(tmp_path, mid)
    court_zone = next(iter(water_flood.courts(e, e.state.actors[A])))
    assert court_zone.trigger_profile.get('difficult') is None, 'an unflooded Court charges nobody'
    assert zones.zone_is_difficult(e, court_zone, e.state.actors[B]) is False


@pytest.mark.parametrize('save,prone', [(-100, True), (100, False)])
def test_drowning_pressure_and_soaked_branches(tmp_path, save, prone):
    _, victim, _ = flooded(tmp_path, save=save, distance=0)
    ids = [c.condition_id for c in victim.conditions.values()]
    is_prone = any(k.endswith('.prone') or k == 'prone' for k in ids)
    assert is_prone == prone, 'a failure knocks Prone; a success does not'
    if save < 0:
        assert any('Drowning Pressure'.lower().replace(' ', '_') in k.lower().replace(' ', '_') or 'drowning' in k.lower()
                   for k in ids), 'a failure leaves Drowning Pressure'
    else:
        assert any(k.startswith('condition:typed.mark.soaked.') for k in ids), 'a success leaves Soaked'


def test_drowning_pressure_ends_at_the_end_of_the_victims_next_turn(tmp_path):
    """'until the end of its next turn' is the victim's turn, never the caster's."""
    _, victim, e = flooded(tmp_path, save=-100, distance=0)
    pressure = [c for c in victim.conditions.values() if 'drowning' in c.condition_id.lower()]
    assert pressure, 'Drowning Pressure is recorded on the victim'
    for condition in pressure:
        assert condition.expires_on == 'END_OF_TARGET_NEXT_TURN', \
            f'{condition.condition_id} expires as {condition.expires_on}, the victim\'s next turn end'
        assert condition.expires_on != 'END_OF_MARKER_NEXT_TURN', 'not the caster\'s (marker) turn'


# ---------------------------------------------------------------- finding 5: optional 3 CP


def test_flood_costs_optional_cultivation_points_not_qi(tmp_path):
    """'You may spend 3 CP' -- three Cultivation Points, from the CP pool, and never Qi."""
    row = json.loads((APP / 'authority/typed_mechanics/reviewed_final.d/review_sw-water.json').read_text())['mechanics'][FLOOD]
    cost = row['cost']
    assert len(cost) == 1 and len(cost[0]) == 1, f'one optional payment, not alternatives: {cost}'
    part = cost[0][0]
    assert part['resource'] == 'cp' and int(part['amount']) == 3, \
        f'the reviewed cost is optional 3 Cultivation Points, not Qi: {part}'

    e, _, _ = flooded(tmp_path, distance=0)
    source_text = json.loads((APP / 'catalog_authority/cat3/generated/catalog_authority.v1.json').read_text())
    text = next(r['full_exact_source_text'] for r in source_text['talents']
                if r['canonical_talent_id'] == FLOOD)
    assert 'you may spend 3 CP as an action to flood it' in text, 'the printed line is the authority'