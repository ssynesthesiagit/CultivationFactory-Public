"""Battle Musician: Constitution keys Cadence talents, Stamina may
pay for an embodied performance, and Opening Phrase is free once a
turn after the Attack action -- through CombatService, the session's
execute_intent flow and a cold reload."""
from combat.factory_compiler import compile_character
from tests.h1_support import sheet
from tests.worker2_support import (ALLY, FOE, OWNER, candidate, fixture,
                                    reload, settle)

INSIGHT = 'insight.battle-musician'
RHYTHMIC_GUARD = 'tianxia.talent.music.rhythmic_guard'
HEALING_HYMN = 'tianxia.talent.music.healing_hymn'
KEEP_THE_MEASURE = 'Keep the Measure'
UNARMED_STRIKE = 'Unarmed Strike'
FREE_TEMP_HP = 'Opening Phrase: Temporary HP (free with the Attack action, Battle Musician)'
STAMINA = 'resource:core.stamina'
QI = 'resource:core.qi'


def _owner_bundle(talents, *, insight=True, con=18, cha=8, cl=11, key='CHA',
                  qi=30, stamina=None):
    """A Music fighter whose Music key ability (Charisma, -1) is not
    their Constitution (+4), so the key-ability swap is observable."""
    document = sheet(talents, cl=cl, key=key)
    for ability in document['ability_scores_and_statistics']['abilities']:
        if ability['ability'] == 'CON':
            ability['score'], ability['modifier'] = con, (con - 10) // 2
        elif ability['ability'] == 'CHA':
            ability['score'], ability['modifier'] = cha, (cha - 10) // 2
    pools = {'name': 'Qi', 'maximum': qi}
    if stamina is not None:
        # "Each Path keeps its own CP pool": a second Path pool the
        # printed Stamina substitution may spend.
        pools['definitions'] = [{'name': 'Stamina', 'max': stamina}]
    document['ability_scores_and_statistics']['primary_resource'] = pools
    if insight:
        document['spheres_and_talents']['cultivation_insight_record_ids'] = [INSIGHT]
    return compile_character(document, actor_id=OWNER, reaction_plan={'ask': True})


def _numbers(bundle, name):
    """A talent's compiled numbers. An Action carries them under
    parameters.typed; a Reaction (the sealed engine runs it itself)
    carries them at the row's top level."""
    for action in bundle['action_catalog']:
        if action['display_name'] == name:
            return action['parameters']['typed']['numbers']
    for reaction in bundle['typed_reactions']:
        if reaction['name'] == name:
            return reaction['numbers']
    raise AssertionError(f'no compiled talent named {name!r}')


def test_cadence_talents_read_constitution(tmp_path):
    # "Use Constitution as your Music key ability for Cadence
    # talents": Rhythmic Guard is Cadence-tagged, so its key-ability
    # modifier (and the technique save DC, which is 8 + PB + the key
    # ability modifier) read Constitution, not the printed Music key
    # ability.
    plain = _numbers(_owner_bundle([RHYTHMIC_GUARD], insight=False), 'Rhythmic Guard')
    keyed = _numbers(_owner_bundle([RHYTHMIC_GUARD]), 'Rhythmic Guard')
    assert plain['key_mod'] == -1 and plain['con_mod'] == 4
    assert keyed['key_mod'] == 4
    assert keyed['save_dc'] == plain['save_dc'] - plain['key_mod'] + keyed['key_mod']


def test_a_talent_that_is_not_cadence_keeps_the_music_key(tmp_path):
    # Healing Hymn is a Chord, not a Cadence talent: the Insight's
    # key-ability rule leaves it on the Music key ability.
    plain = _numbers(_owner_bundle([HEALING_HYMN], insight=False), 'Healing Hymn')
    keyed = _numbers(_owner_bundle([HEALING_HYMN]), 'Healing Hymn')
    assert keyed['key_mod'] == plain['key_mod'] == -1
    assert keyed['save_dc'] == plain['save_dc']


def test_an_embodied_performance_pays_stamina(tmp_path):
    # "You may spend Stamina instead of Cultivation Points": the
    # owner's Qi pool cannot pay for Healing Hymn, so only the
    # Insight's substitution can -- and it pays Stamina.
    combat, table, mid = fixture(
        tmp_path, [HEALING_HYMN],
        owner_bundle=_owner_bundle([HEALING_HYMN], qi=1, stamina=10))
    engine = reload(tmp_path, mid)
    owner = engine.state.actors[OWNER]
    assert owner.resources[QI] == 1
    row = candidate(combat, mid, 'Healing Hymn')
    settle(table, mid, row.candidate_id)
    engine = reload(tmp_path, mid)
    spent = [ev for ev in engine.events if ev.event_type == 'RESOURCE_SPENT'
             and ev.payload.get('resource_id') == STAMINA]
    assert spent and spent[-1].payload['amount'] == 4
    assert engine.state.actors[ALLY].current_hp > 0


def test_the_hymn_is_unpayable_without_the_insight(tmp_path):
    # Without the Insight there is no substitution, so an empty Qi
    # pool leaves the printed CP cost unpaid and the hymn is not
    # offered at all.
    combat, table, mid = fixture(
        tmp_path, [HEALING_HYMN],
        owner_bundle=_owner_bundle([HEALING_HYMN], insight=False, qi=1, stamina=10))
    engine = reload(tmp_path, mid)
    offered = [c for c in engine.legal_candidates()
               if c.display_name == 'Healing Hymn']
    assert not offered


def test_opening_phrase_is_free_after_the_attack_action(tmp_path):
    # "When you take the Attack action while Keeping the Measure, you
    # may use Opening Phrase once during that turn without spending
    # its Bonus Action": the Measure is kept (Bonus Action), the
    # Attack action is taken, and Opening Phrase then runs as a free
    # action -- the ally gains Temporary HP equal to the owner's
    # Proficiency Bonus, and the free use is spent for the turn.
    # The foe stands where the owner perceives it, so the Attack
    # action (an Unarmed Strike) is offered.
    combat, table, mid = fixture(tmp_path, [RHYTHMIC_GUARD], owner_insights=[INSIGHT],
                               foe_position={'x': 2, 'y': 6})
    engine = reload(tmp_path, mid)
    settle(table, mid, candidate(combat, mid, KEEP_THE_MEASURE).candidate_id)
    settle(table, mid, candidate(combat, mid, UNARMED_STRIKE, target=FOE).candidate_id)
    settle(table, mid, candidate(combat, mid, FREE_TEMP_HP, target=ALLY).candidate_id)
    engine = reload(tmp_path, mid)
    granted = [ev for ev in engine.events if ev.event_type == 'TEMP_HP_GRANTED'
               and ev.target_ids == (ALLY,)]
    assert granted and granted[-1].payload['offered'] >= 4
    again = [c for c in engine.legal_candidates() if c.display_name == FREE_TEMP_HP]
    assert not again


def test_opening_phrase_needs_the_attack_action_first(tmp_path):
    # The free Opening Phrase is triggered by the Attack action:
    # after the Measure (itself a Bonus Action, which spends the
    # turn's Bonus Action) but before any Attack action, the free
    # phrase is not offered -- the Attack action has not been taken.
    combat, table, mid = fixture(tmp_path, [RHYTHMIC_GUARD], owner_insights=[INSIGHT],
                               foe_position={'x': 2, 'y': 6})
    engine = reload(tmp_path, mid)
    settle(table, mid, candidate(combat, mid, KEEP_THE_MEASURE).candidate_id)
    free = [c for c in engine.legal_candidates() if c.display_name == FREE_TEMP_HP]
    assert not free


def test_opening_phrase_needs_the_measure(tmp_path):
    # "Use this only while you Keep the Measure": without the Measure
    # the free Opening Phrase is not offered even after the Attack
    # action.
    combat, table, mid = fixture(tmp_path, [RHYTHMIC_GUARD], owner_insights=[INSIGHT],
                               foe_position={'x': 2, 'y': 6})
    engine = reload(tmp_path, mid)
    settle(table, mid, candidate(combat, mid, UNARMED_STRIKE, target=FOE).candidate_id)
    free = [c for c in engine.legal_candidates() if c.display_name == FREE_TEMP_HP]
    assert not free
