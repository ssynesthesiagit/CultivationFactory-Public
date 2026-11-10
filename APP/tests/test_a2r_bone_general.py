"""Bone General: the reserved Death Control slot and the commanded
servant's step, through CombatService transactions and cold replay."""
import pytest
from tests.worker2_support import fixture, candidate, settle, reload, turn, OWNER, ALLY, FOE

TALENT = 'TAL_DEATH_CORPSE_SERVANT'
FORMATION = 'TAL_DEATH_GRAVE_FORMATION'
INSIGHT = 'insight.bone-general'


def setup(tmp_path, *, insight=True, talents=(TALENT,), plan=None, **layout):
    return fixture(tmp_path, list(talents), cl=11,
                   owner_insights=[INSIGHT] if insight else [],
                   owner_plan=plan, seed=f'BONE-{insight}', **layout)


def servants(engine, group):
    return [a for a in engine.state.actors.values()
            if (a.summon or {}).get('owner') == OWNER
            and a.summon.get('group') == group]


def use(combat, table, mid, name, **kw):
    row = candidate(combat, mid, name, target=kw.pop('target', None), at=kw.pop('at', None))
    if kw.pop('auto_ai', False):
        ai_send(combat, table, mid, row.candidate_id)
        return []
    return settle(table, mid, row.candidate_id, **kw)


@pytest.mark.parametrize('insight,expected', [(False, 4), (True, 5)])
def test_the_reserved_slot_raises_the_corpse_servant_count(tmp_path, insight, expected):
    # "Increase your Death Control Limit by 1, but the extra capacity can be
    # used only for Corpse Servants or Lesser Corpse Servants": with the
    # Insight a fifth load-1 Corpse Servant fits, without it the printed
    # Proficiency-Bonus limit holds.
    combat, table, mid = setup(tmp_path, insight=insight,
                               plan={'counts': {'corpse_servant': 6, 'lesser_corpse_servant': 0}})
    engine = reload(tmp_path, mid)
    assert len(servants(engine, 'corpse_servant')) == expected


def test_the_reserved_slot_does_not_fit_a_grave_formation(tmp_path):
    # A Grave Formation costs 3 Control Load; the extra slot is reserved
    # for load-1 Corpse Servants, so the formation count is unchanged.
    combat, table, mid = setup(tmp_path, talents=(FORMATION,),
                               plan={'counts': {'grave_formation': 2, 'corpse_servant': 0}})
    engine = reload(tmp_path, mid)
    assert len(servants(engine, 'grave_formation')) == 1


def test_a_commanded_servant_steps_up_to_10_feet(tmp_path):
    combat, table, mid = setup(tmp_path, plan={'counts': {'corpse_servant': 1, 'lesser_corpse_servant': 0}})
    engine = reload(tmp_path, mid)
    servant = servants(engine, 'corpse_servant')[0]
    before = servant.position
    prompts = use(combat, table, mid, 'Command Death servants',
                  choices={'choice:needle.bone_general_move': [servant.entity_id],
                           'choice:needle.bone_general_step': None})
    engine = reload(tmp_path, mid)
    servant = next(a for a in engine.state.actors.values() if a.entity_id == servant.entity_id)
    # the step is optional: declining it leaves the servant where it stood
    assert (servant.position.x, servant.position.y) == (before.x, before.y)
    assert servant.summon['commanded']


def test_the_step_moves_the_servant(tmp_path):
    combat, table, mid = setup(tmp_path, plan={'counts': {'corpse_servant': 1, 'lesser_corpse_servant': 0}})
    engine = reload(tmp_path, mid)
    servant = servants(engine, 'corpse_servant')[0]
    before = (servant.position.x, servant.position.y)
    # answer the step by walking to the first offered destination
    prompts = use(combat, table, mid, 'Command Death servants',
                  choices={'choice:needle.bone_general_move': [servant.entity_id],
                           'choice:needle.bone_general_step': 'first'})
    engine = reload(tmp_path, mid)
    servant = next(a for a in engine.state.actors.values() if a.entity_id == servant.entity_id)
    after = (servant.position.x, servant.position.y)
    assert after != before
    assert servant.summon['commanded']
    # "may move up to 10 feet": the granted step costs at most 10 feet
    # (a diagonal route can cover three five-foot squares for 10 feet)
    step = [ev for ev in engine.events
            if ev.event_type == 'MOVEMENT_COMMITTED' and ev.actor_id == servant.entity_id]
    assert step and int(step[-1].payload['granted_cost_ft']) <= 10


def ai_send(combat, table, mid, cid, answers=()):
    """Drive one candidate through the table's AI step: the built-in AI's
    own restraint would rather attack than command, so the selected adapter
    forces this candidate while the owner is automatic. This tests the
    plug-in's AI execution, not the AI's policy (hunt31_support.send)."""
    from combat.gate4_adapters import ManualControllerAdapter
    selected = next(c for c in combat._load_session(mid).engine.legal_candidates()
                    if c.candidate_id == cid)
    original = combat.controller

    class Selected:
        def choose_primary_action(self, context):
            legal = combat._load_session(mid).engine.legal_candidates()
            choice = next(c for c in legal
                          if c.source_definition_id == selected.source_definition_id
                          and c.target_ids == selected.target_ids
                          and c.destination == selected.destination)
            context = context.model_copy(update={'legal_candidates': tuple(legal)})
            return ManualControllerAdapter(lambda _: (choice.candidate_id, ())).choose_primary_action(context)

        def __getattr__(self, name):
            return getattr(original, name)

    combat.controller = Selected()
    combat.set_controller_mode(mid, actor_id=OWNER, controller_mode='LOCAL_AUTO')
    try:
        result = table.auto_step(mid, table.state(mid)['last_sequence'], list(answers))
        assert result['status'] == 'COMMITTED', result
        return result
    finally:
        combat.controller = original
        combat.set_controller_mode(mid, actor_id=OWNER, controller_mode='MANUAL')


def test_an_ai_summoner_steps_the_nearest_servant(tmp_path):
    combat, table, mid = setup(tmp_path, plan={'counts': {'corpse_servant': 1, 'lesser_corpse_servant': 0}})
    engine = reload(tmp_path, mid)
    servant = servants(engine, 'corpse_servant')[0]
    before = (servant.position.x, servant.position.y)
    use(combat, table, mid, 'Command Death servants', auto_ai=True)
    engine = reload(tmp_path, mid)
    servant = next(a for a in engine.state.actors.values() if a.entity_id == servant.entity_id)
    after = (servant.position.x, servant.position.y)
    # an AI-controlled summoner walks its servant nearer the foe (or holds it),
    # within the printed 10 feet of granted movement
    assert servant.summon['commanded']
    if after != before:
        step = [ev for ev in engine.events
                if ev.event_type == 'MOVEMENT_COMMITTED' and ev.actor_id == servant.entity_id]
        assert step and int(step[-1].payload['granted_cost_ft']) <= 10


def test_the_step_is_not_offered_without_the_insight(tmp_path):
    combat, table, mid = setup(tmp_path, insight=False,
                               plan={'counts': {'corpse_servant': 1, 'lesser_corpse_servant': 0}})
    engine = reload(tmp_path, mid)
    servant = servants(engine, 'corpse_servant')[0]
    before = (servant.position.x, servant.position.y)
    prompts = use(combat, table, mid, 'Command Death servants')
    engine = reload(tmp_path, mid)
    servant = next(a for a in engine.state.actors.values() if a.entity_id == servant.entity_id)
    assert (servant.position.x, servant.position.y) == before
    assert servant.summon['commanded']
    assert not any(p['context']['reaction_source_id'] == 'choice:needle.bone_general_move'
                   for p in prompts)
