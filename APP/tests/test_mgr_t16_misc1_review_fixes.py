"""Review boundaries and readable investigation records through table reloads."""
import pytest

from combat.ext.drunken_style import NO_PATTERN
from combat.ext.soul_echo import FEATURE, QUESTIONS, RESULT
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from tests.h1_support import ROOT
from tests.worker2_support import OWNER, ALLY, FOE, candidate, fixture, reload, settle, turn


# Runtime feature-block discovery globs the directory; retain this exact input
# when the focused tests are exported to the public runner.
PUBLIC_FIXTURE_INPUTS = ('combat/rules/feature_blocks.d/mgr_t16_misc1.json',)


@pytest.mark.parametrize('feature,name,qualifier', [
    ('TAL_AIR_WIND_SENSE', 'Wind-Sense', 'Ordinary Search'),
    (NO_PATTERN, 'No Pattern to Counter', 'Martial Focus'),
])
@pytest.mark.parametrize('owns', [True, False])
def test_missing_producers_remain_explicit_manual_work_after_table_reload(
        tmp_path, feature, name, qualifier, owns):
    combat, table, mid = fixture(tmp_path, [feature] if owns else [],
        seed='T16-REVIEW-BOUNDARY'+feature+str(owns))
    settle(table, mid, candidate(combat, mid, 'Dodge').candidate_id)
    engine = reload(tmp_path, mid)
    bundle = next(row for row in engine.typed_bundle_documents if row['actor_id'] == OWNER)
    partial = [text for text in bundle['diagnostics']['notes']
               if text.startswith(name+' is partially automated.')]
    skipped = {text for values in bundle['diagnostics']['skipped'].values() for text in values}
    assert bool(partial) is owns
    assert (name in skipped) is owns
    if owns:
        assert qualifier in partial[0] and 'Game Master' in partial[0]
        assert 'Advantage' in partial[0] and 'only to that' in partial[0]
        rows = [row for row in bundle['typed_passives'] if row.get('feature_id') == feature]
        assert len(rows) == 1 and rows[0]['keeps_compiling']
        assert rows[0]['manual_handling'] == partial[0]
    # Owning a consumer never manufactures an unqualified Perception bonus.
    from combat.typed_executor import check_mode
    assert check_mode(engine.state.actors[OWNER], 'WIS', 'Perception', engine=engine) == 'NORMAL'


@pytest.mark.parametrize('place', [False, True])
def test_two_soul_echo_readings_keep_subject_question_and_answer_on_cold_table(tmp_path, place):
    questions = ('residual_spirit', 'silence_origin') if place else ('possession', 'coercion')
    places = ('Old Shrine', 'Stone Bridge')
    subjects = (FOE, ALLY)
    answer = 'A spirit is present'

    def arena(doc):
        doc['terrain_regions'] = []
        doc['map_objects'] = []
        for index, question in enumerate(questions):
            profile = {'dc': 0, 'facts': {question: answer}}
            if not place:
                profile['creature_id'] = subjects[index]
            doc['map_objects'].append({'id': 701+index, 'kind': 'custom',
                'name': places[index], 'x': 4+index, 'y': 5, 'blocks': False,
                'source_profiles': {'soul_echo': profile}})

    combat, table, mid = fixture(tmp_path, [FEATURE], named=True,
        seed='T16-REVIEW-READINGS'+str(place), battlefield_transform=arena)
    for index, question in enumerate(questions):
        turn(table, mid, OWNER)
        target = 'object:map.'+str(701+index) if place else subjects[index]
        label = 'Soul-Echo Hearing: investigate '+('a place' if place else 'a creature')
        prompts = settle(table, mid, candidate(combat, mid, label, target=target).candidate_id,
            picks={'choice:needle.soul_echo_fact': [question]})
        assert any(p['context']['reaction_source_id'] == 'choice:needle.soul_echo_fact' for p in prompts)
        reload(tmp_path, mid)
        if index == 0:
            settle(table, mid, table.state(mid)['menu']['end_turn'])

    engine = reload(tmp_path, mid)
    names = places if place else tuple(engine.state.actors[aid].display_name for aid in subjects)
    readings = [row for row in engine.state.actors[OWNER].conditions.values() if row.condition_id == RESULT]
    assert len(readings) == 2
    for index, name in enumerate(names):
        row = next(row for row in readings if row.data.get('subject_label') == name)
        assert row.data['question'] == questions[index]
        assert row.data['question_label'] == QUESTIONS[questions[index]]
        assert row.data['value'] == answer
        assert all(type(value) in (str, int) for value in row.data.values())

    cold = TabletopService(CombatService(ROOT, tmp_path), tmp_path).state(mid)
    labels = [row['display_name'] for actor in cold['presentation']['actors'] if actor['entity_id'] == OWNER
              for row in actor['conditions'] if row['condition_id'] == RESULT]
    assert len(labels) == 2
    for index, name in enumerate(names):
        label = next(label for label in labels if name in label)
        assert QUESTIONS[questions[index]] in label and answer in label
        assert 'Recorded information' in label
        assert 'object:map.' not in label
