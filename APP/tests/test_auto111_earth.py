"""Earth Round 3: Packed Road Step's printed terrain waiver reaches live movement pricing.

The printed talent (rules_text.json TAL_EARTH_PACKED_ROAD_STEP) has two clauses, and both say
*nonmagical*:

  "Your movement through your own Foundation Spaces does not cost extra movement from nonmagical
   difficult terrain. When you create Foundation Spaces with Set Foundation, choose one willing
   creature you can see. Until the start of your next turn, that creature also ignores nonmagical
   difficult terrain in those spaces. At CL 5, choose two willing creatures. At CL 11, choose three."

Both are answered by the shared ``difficult_exempt`` query, which combat/zones.py difficult_cells
consults when it prices movement. Nonmagical ground is the table's own map terrain, so every case
here lays loose rubble through the arena's ``map_terrain``; ground an ability made gets a case of
its own, because the printed word excludes it.

Every case commits through the table and reloads the fight, so each one fails without the plug-in:
a rough Foundation Space still costs double movement for anyone the choice does not cover.
"""
import pytest
from combat import zones
from combat.ext import earth_responses as earth
from tests.auto_worker1_support import LEFT, RIGHT, act, fight, reload, turn

FOUNDATION = 'EARTH_BASE_SET_FOUNDATION'
PACKED = earth.PACKED_ROAD
WITNESS = 'actor:factory.auto111-witness'
RUBBLE = [{'terrain': 'loose rubble', 'cells': [[x, y] for x in range(2, 5) for y in range(5, 8)]}]
WIDE_RUBBLE = [{'terrain': 'loose rubble', 'cells': [[x, y] for x in range(1, 9) for y in range(5, 8)]}]
# A typed terrain_patch laid by an ability: ground a spell made, which the printed waiver excludes.
SHAKEN = {'type': 'terrain_patch', 'difficult': 'all', 'radius_ft': 10, 'name': 'Shaken ground'}


def _foundation(tmp_path, *, packed=True, cl=15, map_terrain=RUBBLE, **kwargs):
    """A fight whose common floor is the table's own rough ground, with Set Foundation available."""
    talents = [FOUNDATION, *([PACKED] if packed else [])]
    return fight(tmp_path, talents, cl=cl, map_terrain=map_terrain, **kwargs)


def _lay_foundation(table, mid, *, target=LEFT, choose=None, count=None):
    """Set Foundation, answering the printed choice when the table pauses for it.

    Returns the prompt, so a case can read the menu it published.
    """
    result = act(table, mid, FOUNDATION, target_id=target)
    if result['status'] != 'REACTION_REQUIRED':
        return None
    prompt = result['reaction']
    assert earth.PACKED_LABEL in str(prompt), prompt
    options = [o['id'] for o in prompt['choice']['options']]
    wanted = options[:count] if choose is None else [i for i in choose if i in options]
    result = act(table, mid, FOUNDATION, target_id=target,
                 answers=[{**prompt['context'], 'selection': 'USE', 'option_ids': wanted}])
    assert result['status'] == 'COMMITTED', result
    return prompt


def _record(engine, owner_id):
    """The live Packed Road Step record of one owner: its chosen creatures and its spaces."""
    data = earth._packed_data(engine, engine.state.actors[owner_id])
    chosen = [c for c in str(data.get('chosen') or '').split(',') if c]
    return chosen, earth._packed_cells(data.get('cells'))


def _slowed(engine, actor, cells=None):
    """The rough Foundation Spaces this creature still pays extra movement to cross."""
    rough = cells if cells is not None else earth.foundation_cells(engine, engine.state.actors[LEFT])
    assert rough, 'the fixture must lay Foundation Spaces for this talent to cover'
    return rough & set(zones.difficult_cells(engine, actor))


@pytest.mark.parametrize('cl,count', [(1, 1), (5, 2), (11, 3)])
def test_packed_road_step_asks_for_the_printed_number_of_creatures(tmp_path, cl, count):
    combat, table, mid = _foundation(tmp_path, cl=cl, extra_witness=True)
    prompt = _lay_foundation(table, mid, count=count)
    assert prompt['choice']['maximum'] == count, \
        f'the printed count at CL {cl} is {count}, not a deeper character allowance'
    engine = reload(combat, mid)
    owner = engine.state.actors[LEFT]
    chosen, cells = _record(engine, LEFT)
    assert cells, 'the waiver records the Foundation Spaces it covers'
    assert len(chosen) == count, (cl, chosen)
    assert not _slowed(engine, owner), 'the owner is never slowed by their own Foundation'


def test_packed_road_step_answer_never_beats_the_printed_count(tmp_path):
    """An answer asking for more creatures than the printed count grants no more than that count."""
    combat, table, mid = _foundation(tmp_path, cl=1, extra_witness=True)  # CL 1 allows one
    first = act(table, mid, FOUNDATION, target_id=LEFT)
    assert first['status'] == 'REACTION_REQUIRED', first
    options = [o['id'] for o in first['reaction']['choice']['options']]
    assert len(options) > 1, 'the fixture needs more candidates than the printed count allows'
    result = act(table, mid, FOUNDATION, target_id=LEFT,
                 answers=[{**first['reaction']['context'], 'selection': 'USE', 'option_ids': options}])
    assert result['status'] == 'COMMITTED', result
    engine = reload(combat, mid)
    chosen, _ = _record(engine, LEFT)
    assert len(chosen) <= 1, chosen


def test_packed_road_step_covers_the_tables_rough_ground_for_the_chosen_creature(tmp_path):
    combat, table, mid = _foundation(tmp_path, cl=5, extra_witness=True)
    _lay_foundation(table, mid, choose=[LEFT, WITNESS])
    engine = reload(combat, mid)
    owner, ally, other = (engine.state.actors[i] for i in (LEFT, WITNESS, RIGHT))
    chosen, cells = _record(engine, LEFT)
    assert set(chosen) == {LEFT, WITNESS}, chosen
    assert not _slowed(engine, owner, cells)
    assert not _slowed(engine, ally, cells), 'the chosen creature crosses that ground as if it were normal'
    assert _slowed(engine, other, cells), 'a creature the owner did not choose keeps paying'


def test_packed_road_step_does_not_cover_rough_ground_an_ability_made(tmp_path):
    """The printed waiver says *nonmagical*: an ability's own difficult ground is not waived."""
    combat, table, mid = _foundation(tmp_path, cl=5, prepare=[SHAKEN], extra_witness=True)
    assert act(table, mid, 'Prepare', target_id=RIGHT)['status'] == 'COMMITTED'
    _lay_foundation(table, mid, choose=[LEFT, WITNESS])
    engine = reload(combat, mid)
    owner, ally = engine.state.actors[LEFT], engine.state.actors[WITNESS]
    chosen, cells = _record(engine, LEFT)
    assert set(chosen) == {LEFT, WITNESS}, chosen
    assert not cells & zones.nonmagical_difficult_cells(engine, ally), \
        'the fixture must leave no nonmagical ground in those spaces for this case to mean anything'
    assert cells & set(zones.difficult_cells(engine, ally)) == cells, \
        'rough ground an ability made still costs the chosen creature the movement'
    assert cells & set(zones.difficult_cells(engine, owner)) == cells, \
        'and it costs the owner the movement too'


def test_packed_road_step_waiver_ends_at_the_start_of_your_next_turn(tmp_path):
    combat, table, mid = _foundation(tmp_path)
    _lay_foundation(table, mid, choose=[RIGHT])
    engine = reload(combat, mid)
    owner = engine.state.actors[LEFT]
    assert not _slowed(engine, engine.state.actors[RIGHT]), 'it holds on the turn it is given'
    assert [c for c in owner.conditions.values() if c.condition_id == earth.PACKED_RECORD], \
        'the printed choice is a record on its owner'
    turn(table, mid, RIGHT)
    turn(table, mid, LEFT)  # the owner's next turn begins: the printed window closes here
    engine = reload(combat, mid)
    assert _slowed(engine, engine.state.actors[RIGHT]), \
        'the waiver must not last the rest of the fight by accident'
    assert not any(c.condition_id == earth.PACKED_RECORD for c in engine.state.actors[LEFT].conditions.values()), \
        'the spent benefit must leave the sheet with it, not linger as a pill'
    assert not earth._packed_data(engine, engine.state.actors[LEFT])


def test_packed_road_step_is_inert_without_the_talent(tmp_path):
    combat, table, mid = _foundation(tmp_path, packed=False)
    _lay_foundation(table, mid)
    engine = reload(combat, mid)
    owner, other = engine.state.actors[LEFT], engine.state.actors[RIGHT]
    assert not earth.rows(engine, owner, 'packed_road')
    assert not earth._packed_data(engine, owner)
    assert not any(c.condition_id == earth.PACKED_RECORD for c in owner.conditions.values())
    assert _slowed(engine, owner), 'the owner keeps paying for rough ground in its own Foundation'
    assert _slowed(engine, other), 'a character without the talent gets no waiver at all'


@pytest.mark.parametrize('cl', [5, 11])
def test_packed_road_step_ai_chooses_its_own_allies_and_never_an_enemy(tmp_path, cl):
    """Checklist 9: an AI answers the printed choice itself, and never spends it on an opponent.

    One ally and one enemy stand on the table, so an answer that simply filled every slot from the
    visible audience would hand the movement benefit to the enemy."""
    from tests.auto_worker1_support import action_sender

    # Bystander (enemy) sorts before Visitor (ally): CL 5 must prefer the ally,
    # and CL 11 must leave the unused third slot empty instead of helping the enemy.
    combat, table, mid = _foundation(tmp_path, cl=cl, extra_witness=True, right_team='team:factory')
    send = action_sender(combat, table, mid, FOUNDATION, ai=True, target_id=LEFT)
    assert send([])['status'] == 'COMMITTED', 'the AI must resolve the choice, not stall'
    engine = reload(combat, mid)
    chosen, cells = _record(engine, LEFT)
    assert set(chosen) == {LEFT, RIGHT}, chosen
    assert WITNESS not in chosen, 'an enemy is not willing by default'
    data = earth._packed_data(engine, engine.state.actors[LEFT])
    for value in (data['chosen'], data['cells'], data['turn']):
        assert isinstance(value, (str, int)), value
    for pair in str(data['cells']).split(';'):
        x, _, y = pair.partition(',')
        assert x.lstrip('-').isdigit() and y.lstrip('-').isdigit(), pair
    assert cells == earth.foundation_cells(engine, engine.state.actors[LEFT])


def test_packed_road_step_grants_from_two_owners_combine(tmp_path):
    """Two owners with separate Foundation Spaces both chose the same creature: it gets both.

    The second owner also chose a creature that owns the talent itself, so the owner's own clause
    and the gift it was given have to add up rather than one replacing the other."""
    combat, table, mid = _foundation(tmp_path, right_talents=[FOUNDATION, PACKED], map_terrain=WIDE_RUBBLE,
                                     right_team='team:factory', extra_witness=True,
                                     positions={LEFT: {'x': 2, 'y': 6}, RIGHT: {'x': 7, 'y': 6}})
    _lay_foundation(table, mid, choose=[WITNESS])
    first_chosen, first = _record(reload(combat, mid), LEFT)
    turn(table, mid, RIGHT)
    _lay_foundation(table, mid, target=RIGHT, choose=[WITNESS, LEFT])
    engine = reload(combat, mid)
    second_chosen, second = _record(engine, RIGHT)
    assert first_chosen == [WITNESS], first_chosen
    assert set(second_chosen) == {WITNESS, LEFT}, second_chosen
    assert first and second, (sorted(first), sorted(second))
    assert not first & second, 'the fixture must give the two owners separate spaces'
    both = first | second
    for who in (WITNESS, LEFT):
        assert not both & set(zones.difficult_cells(engine, engine.state.actors[who])), \
            f'{who} must keep the waiver in both owners spaces'
    assert first & set(zones.difficult_cells(engine, engine.state.actors[RIGHT])), \
        'a creature the other owner did not choose still pays on that ground'
    assert not second & set(zones.difficult_cells(engine, engine.state.actors[RIGHT])), \
        'its own talent waives its own Foundation'


@pytest.mark.parametrize('mode', ['LOCAL_AUTO', 'API_AUTO'])
def test_packed_road_step_automatic_fallback_only_grants_to_allies(tmp_path, mode):
    """Both automatic controllers use the same allied policy even without a choice provider."""
    combat, table, mid = _foundation(tmp_path, cl=11, extra_witness=True, right_team='team:factory')
    _lay_foundation(table, mid, choose=[LEFT])
    engine = reload(combat, mid)
    engine.typed_control_modes[LEFT] = mode
    engine._active_intent = None  # exercise the hook's deterministic fallback without making an API call
    source = next(row.source_definition_id for row in engine.action_catalog.values()
                  if row.owner_id == LEFT and (row.parameters.get('typed') or {}).get('source') == FOUNDATION)
    earth.packed_road_choice(engine, engine.state.actors[LEFT], 'ACTION', source)
    assert set(_record(engine, LEFT)[0]) == {LEFT, RIGHT}


def test_packed_road_step_record_survives_a_further_table_commit(tmp_path):
    """Checklist 7: the stored record is integers and strings that outlive later table commits."""
    combat, table, mid = _foundation(tmp_path, cl=5, extra_witness=True)
    _lay_foundation(table, mid, count=2)
    engine = reload(combat, mid)
    chosen, cells = _record(engine, LEFT)
    assert len(chosen) == 2, chosen
    assert not _slowed(engine, engine.state.actors[WITNESS])
    assert act(table, mid, 'end')['status'] == 'COMMITTED'  # the owner's own next commit
    same_turn = reload(combat, mid)
    assert _record(same_turn, LEFT) == (chosen, cells), 'a further commit on the owner keeps the record'
    turn(table, mid, RIGHT)
    assert act(table, mid, 'Unarmed Strike', target_id=LEFT)['status'] == 'COMMITTED'
    after = reload(combat, mid)
    assert _record(after, LEFT) == (chosen, cells), 'and so does another creature committing its turn'
    assert not _slowed(after, after.state.actors[WITNESS]), 'and it still works after those commits'


@pytest.mark.parametrize('packed', [False, True])
@pytest.mark.parametrize('magical', [False, True])
def test_packed_road_step_movement_quote_and_commit(tmp_path, packed, magical):
    """Price and spend actual movement, including magical terrain overlapping map rubble."""
    combat, table, mid = _foundation(tmp_path, packed=packed, prepare=[SHAKEN] if magical else [])
    if magical:
        assert act(table, mid, 'Prepare', target_id=RIGHT)['status'] == 'COMMITTED'
    prompt = _lay_foundation(table, mid, choose=[LEFT])
    if packed:
        assert 'nonmagical difficult terrain' in str(prompt)
        condition = next(c for c in reload(combat, mid).state.actors[LEFT].conditions.values()
                         if c.condition_id == earth.PACKED_RECORD)
        assert 'nonmagical difficult terrain' in condition.data['label']
    state = table.state(mid)
    move = next(m for m in state['menu']['moves'] if m['destination']['x'] == 2
                and m['destination']['y'] == 6)
    expected = 5 if packed and not magical else 10
    assert move['cost_ft'] == expected
    before = reload(combat, mid).state.actors[LEFT].movement_remaining_ft
    result = table.act(mid, move['candidate_id'], state['menu']['decision_id'],
                       state['menu']['state_version'], state['last_sequence'], [])
    # This step leaves the adjacent opponent's reach. Resolve that player's
    # unrelated optional attack without changing movement or combat rules.
    assert result['status'] == 'REACTION_REQUIRED', result
    assert result['reaction']['reaction'] == 'Opportunity Attack'
    result = table.act(mid, move['candidate_id'], state['menu']['decision_id'],
                       state['menu']['state_version'], state['last_sequence'],
                       [{**result['reaction']['context'], 'selection': 'DECLINE'}])
    assert result['status'] == 'COMMITTED', result
    actor = reload(combat, mid).state.actors[LEFT]
    assert (actor.position.x, actor.position.y) == (2, 6)
    assert before - actor.movement_remaining_ft == expected
