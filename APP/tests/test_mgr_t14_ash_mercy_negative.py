"""Negative control: paid Ash-Veil Mercy with the foe conscious and unharmed.

Spending Funeral Ash alone must not open the Refined Ash Mercy Boundary.
With the foe conscious and unharmed, the rider must offer no scene, context or
target prompt and grant nothing from the feature.
"""
from combat.factory_compiler import compile_character
from tests.h1_support import sheet
from tests.worker2_support import OWNER, ALLY, FOE, fixture, candidate, settle, turn, reload

FEATURE = 'foundation.red_lotus_ash_returning_v0_2B.refined_ash_mercy_boundary'
POOL = 'resource:foundation.funeral_ash'
SCENE = 'choice:needle.ash_mercy.scene'
CONTEXT = 'choice:needle.ash_mercy.context'
TARGET = 'choice:needle.ash_mercy.target'


def test_paid_mercy_on_conscious_unharmed_foe_offers_and_grants_nothing(tmp_path):
    doc = sheet([FEATURE], foundation={
        'foundation_id': 'red_lotus_ash_returning_v0_2B', 'stage': 'Refined',
        'resource': {'name': 'Funeral Ash', 'resource_id': 'tianxia.resource.test',
                     'maximum': 1, 'current': 1}}, name='Wren')
    doc['identity']['proficiency_bonus'] = 4
    owner = compile_character(doc, actor_id=OWNER, reaction_plan={'ask': True})
    foe = sheet([], name='Mara')
    foe['ability_scores_and_statistics']['hit_points']['maximum'] = 200

    combat, table, mid = fixture(
        tmp_path, [], owner_bundle=owner, ally_talents=['FIRE_TAL_FIREBALL_ART'],
        foe_sheet=foe, positions={OWNER: {'x': 3, 'y': 6}, ALLY: {'x': 4, 'y': 6},
                                  FOE: {'x': 8, 'y': 6}},
        seed='ASH-MERCY-NO-SUBJECT', named=True)
    turn(table, mid, OWNER)
    before = reload(tmp_path, mid)
    assert before.state.actors[OWNER].resources.get(POOL) == 1
    prompts = settle(table, mid,
                     candidate(combat, mid, 'Ash-Veil Mercy', target=OWNER).candidate_id,
                     choices={})
    engine = reload(tmp_path, mid)

    # The paid spend really happened, and the foe stayed conscious and unharmed.
    spends = [e for e in engine.events
              if e.event_type == 'RESOURCE_SPENT' and e.payload.get('resource_id') == POOL]
    assert len(spends) == 1 and int(spends[0].payload.get('amount') or 0) == 1
    assert engine.state.actors[OWNER].resources[POOL] == 0
    assert engine.state.actors[FOE].current_hp == 200 and engine.state.actors[FOE].active

    # No scene, context or target prompt from the rider.
    mercy_prompts = [p for p in prompts
                     if str(p['context'].get('reaction_source_id', '')).startswith(
                         ('choice:needle.ash_mercy', SCENE, CONTEXT, TARGET))]
    assert mercy_prompts == []

    # No restraint fact and no temporary HP granted by the feature.
    assert [e for e in engine.events if e.payload.get('fact_kind') == 'ash_mercy_restraint'] == []
    assert [e for e in engine.events
            if e.event_type == 'TEMP_HP_GRANTED' and e.source_definition_id == FEATURE] == []
