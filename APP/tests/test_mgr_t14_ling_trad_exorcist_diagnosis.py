"""CombatService/table commits and cold reload for Exorcist CL3 Ghost Sight and Name the Intruder.

Designation cases use real table decisions, committed fights and cold reloads. Ghost Sight
cases inspect the sense contract on compiled characters. Ward of Invitation is checked both
as an owner-gated hook contract and on real designation rolls, including cancellation by
Disadvantage. Other native check producers do not yet supply its topic tags.
"""

import pytest

from combat.gate5_service import CombatService
from combat import senses
from combat.ext import exorcist as ex
from combat.typed_executor import bears_mark
from tests.h1_support import ROOT
from tests.r10_fixup_support import cast_sender, commit, fixed_dice
from tests.test_lock2_persistence import act
from tests.test_tabletop_hunt6 import table_fight, on_hold, HOLD, LEFT, RIGHT, ALLY

SENSE = 'tianxia.path.spirit_awakening.feature.spiritual_sense'
NAME = 'tianxia.tradition.spirit.exorcist.feature.ghost_sight_and_name_the_intruder'
DESIGNATION = 'condition:typed.exorcist_designation'
# 35 feet apart: past Spiritual Sense's own 10 feet, well inside Name the Intruder's 60.
FAR = {'team1': [[1, 4], [1, 5]], 'team2': [[8, 4]]}
ADJACENT = {'team1': [[3, 4], [3, 5]], 'team2': [[4, 4]]}


def reload(tmp_path, mid):
    session = CombatService(ROOT, tmp_path)._load_session(mid)
    assert session.verify()['status'] == 'PASS'
    assert session.mechanical.replay()['status'] == 'PASS'
    return session.engine


def choose(option, capture=None):
    """Answer the one Ask-me prompt with ``option``, recording what the prompt actually offered."""
    def chooser(prompt):
        options = (prompt.get('choice') or {}).get('options') or []
        if capture is not None:
            capture['ids'] = [o['id'] for o in options]
            capture['labels'] = [o.get('label') or o.get('text') for o in options]
        match = next((o for o in options if o['id'] == option), None)
        assert match is not None, (option, [o['id'] for o in options])
        return match['id'], True
    return chooser


def named(engine, entity_id):
    return [c for c in engine.state.actors[entity_id].conditions.values() if c.condition_id == DESIGNATION]


@pytest.mark.parametrize('case,dc', [
    ('higher_creature', 17),
    ('higher_creature_known', 17),
    ('higher_creature_with_effect', 17),
    ('matching_concealed', 15),
    ('lower_concealment', 15),
    ('source_action_dc', 16),
    ('source_cultivator_dc', 16),
    ('source_without_inline_authority', 16),
    ('authority_fallback', 17),
])
@pytest.mark.parametrize('roll,status', [(1, 'contested'), (19, 'confirmed')])
def test_designation_contests_commit_and_reload(tmp_path, monkeypatch, case, dc, roll, status):
    """Each contest rolls at the table, using effect/action/Authority DC, even for known labels."""
    if case.startswith('higher_creature'):
        original = CombatService._factory_owner_sheet

        def higher_foe(service, project_id):
            document = original(service, project_id)
            if RIGHT.endswith(project_id):
                document['identity']['cultivation_level'] = 10
                document['ability_scores_and_statistics']['technique_save_dc'] = 17
            return document

        monkeypatch.setattr(CombatService, '_factory_owner_sheet', higher_foe)

    combat, table, mid = table_fight(tmp_path, [SENSE, NAME], cl=6, primary='Resonance',
                                    ally_talents=[], foe_types=(['Ghost', 'Intruder'] if case in ('matching_concealed', 'higher_creature_known')
                                                               else ['Ghost']), starts=ADJACENT)

    def conceal(engine):
        if case in ('higher_creature', 'higher_creature_known'):
            return
        source = 'test:route_concealment'
        source_actor = RIGHT
        data = {'source_cl': 3 if case == 'lower_concealment' else 9}
        if case == 'source_action_dc':
            source = next(aid for aid in engine.state.actors[LEFT].action_ids
                          if ex.st.feature_of(engine.action_catalog[aid]) == NAME)
            source_actor = LEFT
        elif case in ('source_cultivator_dc', 'source_without_inline_authority'):
            source_actor = LEFT
            if case == 'source_without_inline_authority':
                # A retained concealment effect can rely entirely on its recorded source.
                data = {}
        elif case == 'higher_creature_with_effect':
            # A DC 15 concealment masks nothing: the creature's own technique DC 17 answers.
            data['save_dc'] = 15
        elif case != 'authority_fallback':
            data['save_dc'] = dc
        else:
            source_actor = 'test:absent_source'
        engine._apply_condition(engine.state.actors[RIGHT], 'condition:typed.invisible', source,
                                source_actor, expires_on='UNTIL_REMOVED', data=data)

    on_hold(monkeypatch, conceal)
    assert act(table, mid, HOLD)['status'] == 'COMMITTED'
    before = reload(tmp_path, mid)
    assert ex._designation_source_cl(before, before.state.actors[RIGHT]) == (
        10 if case.startswith('higher_creature') else 6)
    fixed_dice(monkeypatch, [roll] * 100)
    designation = 'Intruder'
    commit(cast_sender(combat, table, mid, 'Ghost Sight and Name the Intruder', target=RIGHT),
           choose(designation))
    engine = reload(tmp_path, mid)
    held = named(engine, RIGHT)
    assert len(held) == 1
    assert held[0].data['designation'] == designation
    assert held[0].data['status'] == status
    checks = [e for e in engine.events if e.event_type == 'CHECK_ROLLED'
              and 'Designation' in str(e.payload.get('check'))]
    assert len(checks) == 1
    assert checks[0].payload['dc'] == dc
    assert checks[0].payload['success'] is (status == 'confirmed')
    assert checks[0].payload['actor']['natural_result'] == roll
    assert ('Contested' in held[0].data['label']) is (status == 'contested')


@pytest.mark.parametrize('roll,status', [(1, 'contested'), (19, 'confirmed')])
def test_designation_against_a_higher_source_concealment_is_rolled_and_persists(tmp_path, monkeypatch, roll, status):
    """A freely chosen Designation is not true by fiat: an equal-level creature with higher-source concealment
    answers a real Cultivation Check, and the recorded verdict survives the table commit and reload."""
    combat, table, mid = table_fight(tmp_path, [SENSE, NAME], cl=6, primary='Resonance', ally_talents=[],
                                    foe_types=['Ghost'], starts=ADJACENT)

    def conceal(engine):
        engine._apply_condition(engine.state.actors[RIGHT], 'condition:typed.invisible', 'test:route_concealment',
                                RIGHT, expires_on='UNTIL_REMOVED', data={'source_cl': 9, 'save_dc': 15})

    on_hold(monkeypatch, conceal)
    assert act(table, mid, HOLD)['status'] == 'COMMITTED'
    fixed_dice(monkeypatch, [roll] * 100)
    commit(cast_sender(combat, table, mid, 'Ghost Sight and Name the Intruder', target=RIGHT), choose('Intruder'))

    engine = reload(tmp_path, mid)
    held = named(engine, RIGHT)
    assert len(held) == 1, [(c.condition_id, c.data) for c in engine.state.actors[RIGHT].conditions.values()]
    assert held[0].data['designation'] == 'Intruder'
    assert held[0].data['status'] == status
    # A Ghost is not an Intruder, Curse Source or Restless Dead, so nothing is Resonance Marked.
    assert not bears_mark(engine.state.actors[RIGHT], LEFT, 'Resonance')
    feed = engine.events
    checks = [e for e in feed if e.event_type == 'CHECK_ROLLED' and 'Designation' in str(e.payload.get('check'))]
    assert len(checks) == 1, [e.payload.get('check') for e in feed if e.event_type == 'CHECK_ROLLED']
    assert checks[0].payload['dc'] == 15
    assert checks[0].payload['success'] is (status == 'confirmed')
    assert int(checks[0].payload['actor']['natural_result']) == roll
    if status == 'contested':
        assert 'Contested' in held[0].data['label']
        assert any('Contested' in str(e.payload.get('log') or '') for e in feed
                   if e.event_type == 'PASSIVE_TRIGGERED' and e.actor_id == LEFT)
    else:
        assert held[0].data['label'] == 'Exorcist Designation: Intruder'


@pytest.mark.parametrize('conceal_dc,dc', [(15, 17), (20, 20)])
@pytest.mark.parametrize('roll,status', [(1, 'contested'), (19, 'confirmed')])
def test_designation_keeps_a_higher_creatures_own_authority_beside_a_concealment(tmp_path, monkeypatch,
                                                                                conceal_dc, dc, roll, status):
    """A creature whose Source CL exceeds the Exorcist's keeps its own authority when a
    concealment is also recorded: the diagnosis answers the higher DC. Its Technique DC 17 beats
    a DC 15 concealment (the old code dropped it to 15), while a DC 20 concealment still answers.
    The verdict is recorded by the real table action and survives the commit and cold reload."""
    original = CombatService._factory_owner_sheet

    def higher_foe(service, project_id):
        document = original(service, project_id)
        if RIGHT.endswith(project_id):
            document['identity']['cultivation_level'] = 10
            document['ability_scores_and_statistics']['technique_save_dc'] = 17
        return document

    monkeypatch.setattr(CombatService, '_factory_owner_sheet', higher_foe)
    combat, table, mid = table_fight(tmp_path, [SENSE, NAME], cl=6, primary='Resonance', ally_talents=[],
                                     foe_types=['Ghost'], starts=ADJACENT)

    def conceal(engine):
        engine._apply_condition(engine.state.actors[RIGHT], 'condition:typed.hidden',
                                'test:route_concealment', RIGHT, expires_on='UNTIL_REMOVED',
                                data={'source_cl': 9, 'save_dc': conceal_dc})

    on_hold(monkeypatch, conceal)
    assert act(table, mid, HOLD)['status'] == 'COMMITTED'
    before = reload(tmp_path, mid)
    assert ex._designation_source_cl(before, before.state.actors[RIGHT]) == 10
    fixed_dice(monkeypatch, [roll] * 100)
    commit(cast_sender(combat, table, mid, 'Ghost Sight and Name the Intruder', target=RIGHT),
           choose('Intruder'))

    engine = reload(tmp_path, mid)
    held = named(engine, RIGHT)
    assert len(held) == 1
    assert held[0].data['designation'] == 'Intruder'
    checks = [e for e in engine.events if e.event_type == 'CHECK_ROLLED'
              and 'Designation' in str(e.payload.get('check'))]
    assert len(checks) == 1
    assert checks[0].payload['dc'] == dc
    assert checks[0].payload['success'] is (status == 'confirmed')
    assert held[0].data['status'] == status


@pytest.mark.parametrize('case,dice,mode,natural,status,designation', [
    ('skill_advantage', [1, 19], 'ADVANTAGE', 19, 'confirmed', 'Curse Source'),
    ('skill_disadvantage', [1, 19], 'DISADVANTAGE', 1, 'contested', 'Curse Source'),
    ('skill_unrelated', [1, 19], 'NORMAL', 1, 'contested', 'Curse Source'),
    ('skill_cancelled', [1, 19], 'NORMAL', 1, 'contested', 'Curse Source'),
    ('opponent_matches', [1, 19], 'ADVANTAGE', 19, 'confirmed', 'Curse Source'),
    ('opponent_other', [1, 19], 'NORMAL', 1, 'contested', 'Curse Source'),
    ('ward_advantage_cancels_disadvantage', [1, 19], 'NORMAL', 1, 'contested', 'Intruder'),
])
def test_designation_scoped_roll_modes_commit_and_reload(tmp_path, monkeypatch, case, dice,
                                                        mode, natural, status, designation):
    """Scoped conditions and the native Surface Thoughts hook affect the actual diagnosis roll.

    Conditions are deterministic fixture setup, not evidence of acquiring Surface Thoughts.
    The Exorcist is acquired through compilation and its diagnosis uses the real table action.
    Curse Source does not receive Ward of Invitation, so each scoped rule is the only source of
    the mode under test and a broken rule changes the result. The Intruder case keeps Ward in the
    fixture: its Advantage must cancel an existing Cultivation Disadvantage to NORMAL.
    Low-first dice distinguish Normal (contested) from Advantage (confirmed) after reload.
    """
    from combat.ext.riders14_eye import THOUGHTS

    combat, table, mid = table_fight(tmp_path, [SENSE, NAME], cl=6, primary='Resonance',
                                    ally_talents=[], foe_types=['Ghost'], starts=ADJACENT)

    def prepare(engine):
        engine._apply_condition(engine.state.actors[RIGHT], 'condition:typed.invisible',
                                'test:route_concealment', RIGHT, expires_on='UNTIL_REMOVED',
                                data={'source_cl': 9, 'save_dc': 15})
        if case.startswith('opponent_'):
            engine._apply_condition(engine.state.actors[LEFT], THOUGHTS, 'test:thoughts', LEFT,
                                    expires_on='UNTIL_REMOVED',
                                    data={'target_id': RIGHT if case == 'opponent_matches' else ALLY})
        else:
            rules = {'Insight' if case == 'skill_unrelated' else 'Cultivation':
                     'DISADVANTAGE' if case in ('skill_disadvantage', 'ward_advantage_cancels_disadvantage')
                     else 'ADVANTAGE'}
            if case == 'skill_cancelled':
                rules['ALL'] = 'DISADVANTAGE'
            engine._apply_condition(engine.state.actors[LEFT], 'condition:typed.check_mode',
                                    'test:scoped_check', LEFT, expires_on='UNTIL_REMOVED',
                                    data={'rule': {'check_mode': rules}})

    on_hold(monkeypatch, prepare)
    assert act(table, mid, HOLD)['status'] == 'COMMITTED'
    fixed_dice(monkeypatch, dice * 50)
    commit(cast_sender(combat, table, mid, 'Ghost Sight and Name the Intruder', target=RIGHT),
           choose(designation))
    engine = reload(tmp_path, mid)
    checks = [e for e in engine.events if e.event_type == 'CHECK_ROLLED'
              and 'Designation' in str(e.payload.get('check'))]
    assert len(checks) == 1
    assert checks[0].payload['actor']['mode'] == mode
    assert checks[0].payload['actor']['natural_result'] == natural
    assert checks[0].payload['dc'] == 15
    assert checks[0].payload['success'] is (status == 'confirmed')
    assert named(engine, RIGHT)[0].data['designation'] == designation
    assert named(engine, RIGHT)[0].data['status'] == status


@pytest.mark.parametrize('order,dc', [
    (('weak', 'strong'), 20),
    (('strong', 'weak'), 20),
    (('strong', 'unknown'), None),
    (('unknown', 'strong'), None),
])
@pytest.mark.parametrize('roll,status', [(1, 'contested'), (19, 'confirmed')])
def test_designation_answers_the_strongest_differently_sourced_protection(tmp_path, monkeypatch, order, dc, roll, status):
    """Two concealments from different sources: the diagnosis answers the strongest one, in either
    application order, so a DC 10 concealment never masks a DC 20 one. A protection whose authority is
    not recorded could be the strongest, so it leaves the Designation contested without a roll."""
    combat, table, mid = table_fight(tmp_path, [SENSE, NAME], cl=6, primary='Resonance', ally_talents=[],
                                     foe_types=['Ghost'], starts=ADJACENT)

    def conceal(engine):
        for key in order:
            spec = CONCEALMENTS[key]
            engine._apply_condition(engine.state.actors[RIGHT], spec['condition'], spec['source'],
                                    spec['actor'], expires_on='UNTIL_REMOVED', data=dict(spec['data']))

    on_hold(monkeypatch, conceal)
    assert act(table, mid, HOLD)['status'] == 'COMMITTED'
    fixed_dice(monkeypatch, [roll] * 100)
    commit(cast_sender(combat, table, mid, 'Ghost Sight and Name the Intruder', target=RIGHT), choose('Intruder'))

    engine = reload(tmp_path, mid)
    held = named(engine, RIGHT)
    assert len(held) == 1
    assert held[0].data['designation'] == 'Intruder'
    checks = [e for e in engine.events if e.event_type == 'CHECK_ROLLED'
              and 'Designation' in str(e.payload.get('check'))]
    if dc is None:
        assert not checks, [e.payload.get('check') for e in checks]
        assert held[0].data['status'] == 'contested'
        assert 'Contested' in held[0].data['label']
        assert any('authority is not recorded' in str(e.payload.get('log') or '') for e in engine.events
                   if e.event_type == 'PASSIVE_TRIGGERED' and e.actor_id == LEFT)
    else:
        assert len(checks) == 1, [e.payload.get('check') for e in engine.events if e.event_type == 'CHECK_ROLLED']
        assert checks[0].payload['dc'] == dc
        assert checks[0].payload['success'] is (status == 'confirmed')
        assert held[0].data['status'] == status


# Two differently sourced concealments plus one with no recorded authority. ``Concealment`` rows are
# fixture setup; the designation itself is reached through the real table action above.
CONCEALMENTS = {
    'weak': {'condition': 'condition:typed.invisible', 'source': 'test:route_concealment_weak',
             'actor': ALLY, 'data': {'source_cl': 3, 'save_dc': 10}},
    'strong': {'condition': 'condition:typed.hidden', 'source': 'test:route_concealment_strong',
               'actor': LEFT, 'data': {'source_cl': 9, 'save_dc': 20}},
    'unknown': {'condition': 'condition:typed.invisible', 'source': 'test:route_concealment_unknown',
                'actor': 'test:absent_source', 'data': {}},
}


@pytest.mark.parametrize('key_mod,expected', [(0, 14), (-1, 13), (4, 18)])
def test_designation_authority_fallback_keeps_recorded_key_modifier(key_mod, expected):
    """Resolver contract: a source action without a DC can still record its key modifier."""
    from types import SimpleNamespace

    action = SimpleNamespace(parameters={'typed': {'numbers': {'cl': 9, 'key_mod': key_mod}}})
    engine = SimpleNamespace(action_catalog={'source:concealment': action},
                             state=SimpleNamespace(actors={}))
    condition = SimpleNamespace(data={'source_cl': 9}, source_definition_id='source:concealment',
                                source_actor_id='source:absent')
    assert ex._designation_dc(engine, condition) == expected


def test_all_five_printed_designations_are_offered_and_only_the_three_marking_ones_mark(tmp_path, monkeypatch):
    """The printed Designation list has five entries and every one stays reachable; choosing Host on
    a spirit marks nothing, because only Intruder/Curse Source/Restless Dead earn the mark."""
    combat, table, mid = table_fight(tmp_path, [SENSE, NAME], cl=6, primary='Resonance', ally_talents=[],
                                    foe_types=['Spirit'], starts=ADJACENT)
    fixed_dice(monkeypatch, [19] * 100)
    offered = {}
    commit(cast_sender(combat, table, mid, 'Ghost Sight and Name the Intruder', target=RIGHT),
           choose('Host', offered))

    assert set(ex.CHOICE_DESIGNATIONS) <= set(offered['ids']), offered['ids']
    # Each option says what the designation means to a player who knows only basic D&D; the value
    # recorded in the fight stays the stable printed id.
    for option_id in ex.CHOICE_DESIGNATIONS:
        label = offered['labels'][offered['ids'].index(option_id)]
        assert label != option_id, label
        assert label.startswith(option_id) and len(label) > len(option_id) + 10, label
    assert 'possessing' in offered['labels'][offered['ids'].index('Intruder')]
    assert 'willing' in offered['labels'][offered['ids'].index('Lawful Guest')]
    engine = reload(tmp_path, mid)
    held = named(engine, RIGHT)
    assert held[0].data['designation'] == 'Host'
    assert held[0].data['status'] == 'confirmed'
    assert not bears_mark(engine.state.actors[RIGHT], LEFT, 'Resonance')


@pytest.mark.parametrize('kind,expected', [('Ghost', 60), ('Cursed', 60), ('Animated Corpse', 60),
                                           ('Funerary Disturbance', 60), ('Humanoid', 10), ('Intruder', 10)])
def test_ghost_sight_perceives_the_printed_spirit_and_disturbance_kinds_only(tmp_path, monkeypatch, kind, expected):
    """Printed Ghost Sight perceives spirits, curses, spiritual contamination, corpse animation and
    funerary disturbance; it stays no general Blindsight and never reaches a mere designation label."""
    combat, table, mid = table_fight(tmp_path, [SENSE, NAME], cl=6, primary='Resonance', ally_talents=[SENSE],
                                    foe_types=[kind], starts=FAR)
    engine = reload(tmp_path, mid)
    viewer, seen = engine.state.actors[LEFT], engine.state.actors[RIGHT]
    assert engine._distance_actor_to_actor(viewer, seen) > 10
    assert senses.reach(engine, viewer, 'spiritual_sense', seen) == expected
    # Not general Blindsight: the plain sense row, empty cells and another viewer are unchanged.
    assert senses.reach(engine, viewer, 'spiritual_sense', seen, unrestricted_only=True) == 10
    assert senses.reach(engine, viewer, 'spiritual_sense', senses.cell_probe(seen.position)) == 0
    assert senses.reach(engine, engine.state.actors[ALLY], 'spiritual_sense', seen) == 10


def test_ward_of_invitation_answers_only_its_owner_and_its_printed_questions(tmp_path, monkeypatch):
    """Ward of Invitation is a pure, owner-gated mode query: the ally who lacks the feature is
    untouched, an unrelated Cultivation Check is untouched, and no topic is inferred from prose."""
    combat, table, mid = table_fight(tmp_path, [SENSE, NAME], cl=6, primary='Resonance', ally_talents=[],
                                    foe_types=['Ghost'], starts=FAR)
    engine = reload(tmp_path, mid)
    owner, stranger, seen = (engine.state.actors[who] for who in (LEFT, ALLY, RIGHT))
    assert ex.ward_of_invitation_mode(engine, owner, 'WIS', 'Cultivation', seen, ('possession',)) == 'ADVANTAGE'
    assert ex.ward_of_invitation_mode(engine, owner, 'WIS', 'Cultivation', seen, ('spirit bond', 'coerced')) == 'ADVANTAGE'
    assert ex.ward_of_invitation_mode(engine, stranger, 'WIS', 'Cultivation', seen, ('possession',)) is None
    assert ex.ward_of_invitation_mode(engine, owner, 'WIS', 'Insight', seen, ('possession',)) is None
    assert ex.ward_of_invitation_mode(engine, owner, 'WIS', 'Cultivation', seen, ('heavy cover',)) is None
    assert ex.ward_of_invitation_mode(engine, owner, 'WIS', 'Cultivation', seen, ()) is None
    assert not named(engine, ALLY) and not named(engine, RIGHT)


def test_ward_of_invitation_advantage_is_used_by_table_designation_check(tmp_path, monkeypatch):
    """The compiled Name the Intruder action commits, reloads and applies Ward's Advantage to
    the actual contested Cultivation Check; coverage is part of the designation-mode cases above."""
    combat, table, mid = table_fight(tmp_path, [SENSE, NAME], cl=6, primary='Resonance', ally_talents=[],
                                    foe_types=['Ghost'], starts=ADJACENT)
    def conceal(engine):
        engine._apply_condition(engine.state.actors[RIGHT], 'condition:typed.invisible',
                                'test:route_concealment', RIGHT, expires_on='UNTIL_REMOVED',
                                data={'source_cl': 9, 'save_dc': 15})
    on_hold(monkeypatch, conceal)
    assert act(table, mid, HOLD)['status'] == 'COMMITTED'
    fixed_dice(monkeypatch, [1, 19] * 50)
    commit(cast_sender(combat, table, mid, 'Ghost Sight and Name the Intruder', target=RIGHT), choose('Intruder'))
    engine = reload(tmp_path, mid)
    check = next(e for e in engine.events if e.event_type == 'CHECK_ROLLED'
                 and 'Designation' in str(e.payload.get('check')))
    assert check.payload['actor']['mode'] == 'ADVANTAGE'
    assert check.payload['actor']['natural_result'] == 19
    assert named(engine, RIGHT)[0].data['status'] == 'confirmed'
