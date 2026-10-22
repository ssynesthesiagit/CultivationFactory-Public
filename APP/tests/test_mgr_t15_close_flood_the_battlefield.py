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
  * ``test_printed_push_is_mandatory_not_a_choice`` -- the failure push moves 30 feet and the success
    push 10 feet, full distance: no "do not move it" option exists, so a caster-supplied zero is
    ignored and the printed displacement stands; ``test_flood_answers_no_optional_push_distance``
    keeps the optional-distance seam off this plug-in.
  * ``test_drowning_pressure_ends_at_the_end_of_the_victims_next_turn`` -- the victim's deadline, and
    the floodwater marker's own "until the start of your next turn" (the caster's).
  * ``test_flood_costs_three_cultivation_points_from_the_path_pool`` -- "you may spend 3 CP", one
    optional payment; the engine's CP mapping is the character's Path pool (Qi here), and the record is
    matched by its source hash so a scrambled printed string does not break the check.
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


def flooded(tmp_path, *, save=-100, start_out=None, zero_pick=False):
    """Play Flood with an active Court and return (engine, recipient actor state, engine again).

    When `start_out` is a list, the recipient's position before Flood is appended to it.
    `zero_pick=True` answers the old optional-distance prompt with "Do not move it": the answer is
    ignored because the printed push is mandatory, so the creature still moves the printed distance.
    """
    combat, table, mid = setup(tmp_path, save=save)
    settle(table, mid, candidates(combat, mid, COURT)[0])
    if start_out is not None:
        p = engine(combat, mid).state.actors[B].position
        start_out.append((p.x, p.y))
    picks = flood_recipients()
    if zero_pick:
        picks[f'choice:{FLOOD.lower()}.moved_distance'] = ['0']
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
    other = type('Other', (), {'entity_id': 'actor:factory.00009999', 'team_id': 'team2'})()
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


def flood_zones(e, source):
    """Every live zone this caster's action of ``source`` created."""
    found = []
    for zone in e.state.zones.values():
        action = e.action_catalog.get(zone.source_definition_id)
        typed = (action.parameters.get('typed') or {}) if action else {}
        if zone.owner_id == A and typed.get('source') == source:
            found.append(zone)
    return found


def test_flooded_court_is_difficult_only_for_creatures_without_swim_speed(tmp_path):
    """The rider's exact wording: without Swim Speed is difficult, with it is not.

    Both areas the rider covers are checked: the flooded Court and, where the shared compiler created
    it, the Flood's own 60-foot emanation (``_zone_spec`` reads the printed rider, so under public CI's
    scrambled strings that second zone does not exist and this loop is empty; the Court assertions
    still run).
    """
    from combat import zones

    e, victim, _ = flooded(tmp_path)
    court_zone = next(iter(water_flood.courts(e, e.state.actors[A])))
    flood_area = flood_zones(e, FLOOD)
    assert court_zone.trigger_profile.get('flooded_by') == A, 'the flood makes the Domain difficult'
    assert zones.zone_is_difficult(e, court_zone, victim) is True, 'a creature that cannot swim is charged'
    assert water_flood.floodwater_is_difficult(e, victim, court_zone) is None, 'cannot swim: not excused'
    for zone in flood_area:
        assert zones.zone_is_difficult(e, zone, victim) is True, 'the flood area charges it too'
        assert water_flood.floodwater_is_difficult(e, victim, zone) is None, 'cannot swim: not excused here'

    def grants_swim(engine, actor):
        return 30 if actor.entity_id == B else None

    ext.hook('swim_speed')(grants_swim)
    try:
        assert water_flood.floodwater_is_difficult(e, victim, court_zone) is True, 'swims: excused'
        assert zones.zone_is_difficult(e, court_zone, victim) is False, 'the printed exemption reaches the terrain reader'
        for zone in flood_area:
            assert water_flood.floodwater_is_difficult(e, victim, zone) is True, 'swims: excused here too'
            assert zones.zone_is_difficult(e, zone, victim) is False, 'and from the flood area as well'
    finally:
        ext._HOOKS['swim_speed'].remove(grants_swim)


# ---------------------------------------------------------------- finding 4: the printed moves


@pytest.mark.parametrize('save,distance', [(-100, 30), (100, 10)])
def test_printed_push_is_mandatory_not_a_choice(tmp_path, save, distance):
    """The printed move is mandatory: "moved 30 feet" / "it is moved 10 feet", never "up to N".

    The old ``forced_movement_distance`` answer encoded "Do not move it" as a legal choice, making a
    mandatory printed displacement optional. A caster-supplied zero is now ignored, so the creature
    travels the full printed distance into a legal space, and
    ``test_flood_answers_no_optional_push_distance`` keeps the optional seam off this ability.
    """
    start_out = []
    _, victim, _ = flooded(tmp_path, save=save, start_out=start_out, zero_pick=True)
    start = start_out[0]
    end = (victim.position.x, victim.position.y)
    assert end != start, 'the printed displacement may not be declined'
    assert manhattan(start, end) * 5 == distance, f'moved the printed {distance} feet, not less'


def test_flood_answers_no_optional_push_distance():
    """The printed push is mandatory, so this plug-in answers no optional-distance seam.

    ``forced_movement_distance`` is documented for optional push/pull choices only. Flood used to
    answer it with a 0-to-maximum menu whose own test called the result "the caster's choice"; the
    printed clause is not optional, so no provider from this module may reappear.
    """
    from combat import ext

    providers = [fn for fn in ext._HOOKS.get('forced_movement_distance', [])
                 if getattr(fn, '__module__', '') == 'combat.ext.water_flood']
    assert providers == [], f'Flood must not offer a distance choice: {providers}'


def manhattan(a, b):
    return abs(a[0] - b[0]) + abs(a[1] - b[1])


def test_unflooded_court_is_not_water_for_anyone(tmp_path):
    """The Court's own printed rider: the Domain is not physical water until a floodwater talent is used.

    This plug-in owns the floodwater state: without Flood there is no marker on any creature and the
    Court carries no ``flooded_by`` owner, so nothing here excuses or charges ground on its behalf. The
    zone's own ``difficult`` policy is the shared compiler's reading of the Court's rider text
    ("hostile creatures treat your Basins and Currents as Difficult Terrain", factory_compiler
    ``_zone_spec``); that is the Court record's concern and is not asserted here.
    """
    combat, table, mid = setup(tmp_path)
    settle(table, mid, candidates(combat, mid, COURT)[0])
    _, _, e = cold(tmp_path, mid)
    court_zone = next(iter(water_flood.courts(e, e.state.actors[A])))
    assert court_zone.trigger_profile.get('flooded_by') is None, 'an unflooded Court has no floodwater owner'
    for actor in e.state.actors.values():
        assert not water_flood.flooded_by(actor, A), 'no creature carries a floodwater marker'
        assert water_flood.floodwater_is_difficult(e, actor, court_zone) is None, \
            'the plug-in neither charges nor excuses ground without a flood'
    assert not flood_zones(e, FLOOD), 'an unflooded Court leaves no floodwater area'


@pytest.mark.parametrize('save,prone', [(-100, True), (100, False)])
def test_drowning_pressure_and_soaked_branches(tmp_path, save, prone):
    _, victim, _ = flooded(tmp_path, save=save)
    ids = [c.condition_id for c in victim.conditions.values()]
    is_prone = any(k.endswith('.prone') or k == 'prone' for k in ids)
    assert is_prone == prone, 'a failure knocks Prone; a success does not'
    if save < 0:
        assert any('Drowning Pressure'.lower().replace(' ', '_') in k.lower().replace(' ', '_') or 'drowning' in k.lower()
                   for k in ids), 'a failure leaves Drowning Pressure'
    else:
        assert any(k.startswith('condition:typed.mark.soaked.') for k in ids), 'a success leaves Soaked'


def test_drowning_pressure_ends_at_the_end_of_the_victims_next_turn(tmp_path):
    """'until the end of its next turn' is the victim's turn, never the caster's.

    The floodwater marker itself is the printed "until the start of your next turn", which is the
    caster's next start: the engine keeps that separate from the victim's pressure deadline.
    """
    _, victim, e = flooded(tmp_path, save=-100)
    pressure = [c for c in victim.conditions.values() if 'drowning' in c.condition_id.lower()]
    assert pressure, 'Drowning Pressure is recorded on the victim'
    for condition in pressure:
        assert condition.expires_on == 'END_OF_HOLDER_NEXT_TURN', \
            f'{condition.condition_id} expires as {condition.expires_on}, the victim\'s next turn end'
        assert condition.expires_on != 'END_OF_MARKER_NEXT_TURN', 'not the caster\'s (marker) turn'
    flood = [c for c in victim.conditions.values() if c.condition_id.startswith(water_flood.FLOOD_MARK)]
    assert flood, 'the floodwater marker is recorded on a chosen creature'
    for condition in flood:
        assert condition.expires_on == 'START_OF_SOURCE_NEXT_TURN', \
            f'{condition.condition_id} expires as {condition.expires_on}, the caster\'s next turn start'


# ---------------------------------------------------------------- finding 5: optional 3 CP


def test_flood_costs_three_cultivation_points_from_the_path_pool(tmp_path):
    """'You may spend 3 CP' -- one optional 3 CP payment, and the Path pool pays it, as the engine maps CP.

    ``factory_compiler._one_way`` resolves a printed ``cp`` cost through ``_choose_pool``: "CP means the
    character's current Path resource" (Core Rules Reference). This Qi character's Path pool is Qi, so
    the payment shows up as 3 Qi; the printed cost is not an alternative and never a second pool. The
    printed sentence is matched by its source record, not by its characters, because public CI
    scrambles printed strings.
    """
    row = json.loads((APP / 'authority/typed_mechanics/reviewed_final.d/review_sw-water.json').read_text())['mechanics'][FLOOD]
    cost = row['cost']
    assert len(cost) == 1 and len(cost[0]) == 1, f'one optional payment, not alternatives: {cost}'
    part = cost[0][0]
    assert part['resource'] == 'cp' and int(part['amount']) == 3, \
        f'the reviewed cost is optional 3 CP, not a Qi amount printed as Qi: {part}'
    assert row['text_sha256'] == '1b90f7efd78c2c7b82e9b85bd4beb93cb640624544821f9c20941dabdfee2063', \
        'the reviewed row is the printed Flood record (source hash), so the cost belongs to it'

    e, _, _ = flooded(tmp_path)
    source_text = json.loads((APP / 'catalog_authority/cat3/generated/catalog_authority.v1.json').read_text())
    catalog = next(r for r in source_text['talents'] if r['canonical_talent_id'] == FLOOD)
    assert catalog['source_provenance']['source_context_sha256'] == row['text_sha256'], \
        'the catalog row carries the same source identity'
    assert catalog['minimum_cl'] == 15 and catalog['owning_canonical_sphere_id'] == 'tianxia.sphere.water'


# ---------------------------------------------------------------- finding 1 (F5 review): the Court keeps its own difficulty


def court_difficulty(engine):
    zone = next(iter(water_flood.courts(engine, engine.state.actors[A])))
    return zone.trigger_profile.get('difficult')


@pytest.mark.parametrize('before', ['all', 'hostile', None])
def test_flood_restores_the_courts_own_difficulty_at_turn_start(tmp_path, before):
    """Flood then the caster's next turn: the Court's own difficulty policy is what it was before Flood.

    The unit-level half of the Court regression. The compiler's value for the Court's rider differs
    between private and public CI, so the pre-flood policy is seeded here; without the save/restore the
    turn start pops it and the Court loses its difficulty for the rest of the fight (the F5 review).
    """
    combat, table, mid = setup(tmp_path)
    settle(table, mid, candidates(combat, mid, COURT)[0])
    e = cold(tmp_path, mid)[2]
    zone = next(iter(water_flood.courts(e, e.state.actors[A])))
    if before is None:
        zone.trigger_profile.pop('difficult', None)
    else:
        zone.trigger_profile['difficult'] = before
    owner = e.state.actors[A]
    water_flood.flood_terrain(e, owner)
    assert zone.trigger_profile['difficult'] == 'hostile', 'Flood makes the Court difficult for hostiles'
    water_flood.clear_flood_terrain(e, owner)
    assert zone.trigger_profile.get('difficult') == before, 'the turn start restores the pre-flood policy'
    assert 'flooded_by' not in zone.trigger_profile
    assert 'difficult_before_flood' not in zone.trigger_profile


def test_court_difficulty_survives_flood_turn_and_cold_reload(tmp_path):
    """Table level: play a Court, record its policy, play Flood, reach the caster's next turn, reload cold.

    The policy recorded before Flood must equal the policy after the turn start, and the saved value must
    survive the table commit and reload (strings only, no objects).
    """
    combat, table, mid = setup(tmp_path)
    settle(table, mid, candidates(combat, mid, COURT)[0])
    before = court_difficulty(engine(combat, mid))
    settle(table, mid, candidates(combat, mid, FLOOD)[0], flood_recipients())
    flooded_engine = cold(tmp_path, mid)[2]
    assert court_difficulty(flooded_engine) == 'hostile'
    assert next(iter(water_flood.courts(flooded_engine, flooded_engine.state.actors[A]))).trigger_profile[
        'difficult_before_flood'] == str(before or '')
    settle(table, mid, next(c for c in engine(combat, mid).legal_candidates() if c.display_name == 'End turn'))
    turn(combat, table, mid, B)
    settle(table, mid, next(c for c in engine(combat, mid).legal_candidates() if c.display_name == 'End turn'))
    turn(combat, table, mid, A)
    after = cold(tmp_path, mid)[2]
    zone = next(iter(water_flood.courts(after, after.state.actors[A])))
    assert zone.trigger_profile.get('difficult') == before, 'the Court has its own pre-flood difficulty again'
    assert 'flooded_by' not in zone.trigger_profile
    assert 'difficult_before_flood' not in zone.trigger_profile
