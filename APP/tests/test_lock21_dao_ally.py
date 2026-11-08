"""Dao ally weights act on useful recovery through accepted Table actions."""
import pytest

from combat.gate2_runtime_models import ActionDefinition, EconomyKind
from combat.gate4_models import DecisionContext, LocalControllerPolicy
from factory_authoring.sphere_dao import character_dao, controller_policy
from tests.test_lock_choices import install
from tests.test_lock16_ai_support import checked, context
from tests.test_tabletop_hunt6 import table_fight, on_hold, LEFT, ALLY, RIGHT, HOLD
from tests.test_lock2_persistence import act


def component(score, name):
    return next(c.value for c in score.components if c.component == name)


@pytest.mark.parametrize('kind', ['healing', 'temp_hp'])
def test_dao_helps_wounded_teammate_before_equally_wounded_self(monkeypatch, tmp_path, kind):
    def actions(info):
        return [ActionDefinition(source_definition_id='test:aid:' + info['actor_id'],
            display_name='Restore an ally', owner_id=info['actor_id'], economy=EconomyKind.BONUS_ACTION,
            resolution_kind='TYPED', target_kind='ALLY_OR_SELF', range_ft=60,
            parameters={'typed': {'numbers': info['numbers'],
                'effects': [{'type': kind, 'flat': 12, 'applies_to': 'target'}]}})]
    install(monkeypatch, 'compile_actions', actions)
    def injury(engine):
        for aid in (LEFT, ALLY):
            engine._commit_damage(engine.state.actors[aid], 24, 'FORCE', 'test:injury', RIGHT, None, reaction_depth=0)
    on_hold(monkeypatch, injury)
    combat, table, mid = table_fight(tmp_path, ['tianxia.talent.life.greater_mend'], ally_talents=[])
    assert act(table, mid, HOLD)['status'] == 'COMMITTED'
    engine = checked(combat, tmp_path, mid)
    before = (engine.state.model_dump(mode='json'), len(engine.events), len(engine.rolls))
    ctx = context(combat, mid)
    assert ctx.policy.support_wounded_allies
    rows = [c for c in ctx.legal_candidates if c.source_definition_id == 'test:aid:' + LEFT]
    mine = next(c for c in rows if c.target_ids == (LEFT,))
    theirs = next(c for c in rows if c.target_ids == (ALLY,))
    score = lambda c, context=ctx: combat.controller._score_candidate(context, c, ())
    assert component(score(theirs), 'ally_support') == 12 * ctx.policy.weights['ally_support']
    assert component(score(mine), 'ally_support') == 0
    assert score(theirs).total > score(mine).total
    assert component(score(theirs), 'defeat_prevention_or_finish') == 0
    assert DecisionContext.model_validate_json(ctx.model_dump_json()) == ctx
    assert before == (engine.state.model_dump(mode='json'), len(engine.events), len(engine.rolls))
    # Actual controller selection with the real context and equally priced choices.
    narrowed = ctx.model_copy(update={'legal_candidates': (mine, theirs)})
    assert combat.controller.choose_primary_action(narrowed).intent.candidate_id == theirs.candidate_id
    combat.set_controller_mode(mid, actor_id=LEFT, controller_mode='LOCAL_AUTO')
    assert table.auto_step(mid, 0, [])['status'] == 'COMMITTED'
    fresh = checked(combat, tmp_path, mid)
    target = fresh.state.actors[ALLY]
    # The complete menu also offers real Mend; either useful recovery is valid.
    assert target.current_hp > target.maximum_hp - 24 or target.temporary_hp > 0
    # Legacy policies and old serialized contexts omit the opt-in and retain their scores.
    old = ctx.policy.model_dump(mode='json')
    old.pop('support_wounded_allies')
    legacy = LocalControllerPolicy.model_validate(old)
    assert 'support_wounded_allies' not in legacy.model_dump(mode='json')
    assert component(score(theirs, ctx.model_copy(update={'policy': legacy})), 'ally_support') == 0


@pytest.mark.parametrize('recipient', ['self', 'enemy', 'healthy', 'inactive', 'empty'])
def test_no_credit_for_unhelpful_or_nonallied_recovery(recipient):
    from tests.test_combat_gate4_controller import engine, choose, AN, BAI, LEE
    e = engine('L21-ALLY-INERT')
    _, ctx = choose(e, AN)
    policy = LocalControllerPolicy.model_validate(controller_policy(character_dao({'tianxia.sphere.life': 5}), AN))
    aid = AN if recipient == 'self' else BAI if recipient == 'enemy' else LEE
    actors = tuple(a.model_copy(update={'current_hp': a.maximum_hp if recipient == 'healthy' else 1,
        'active': recipient != 'inactive'}) if a.entity_id == aid else a for a in ctx.actors)
    row = ctx.legal_candidates[0].model_copy(update={'source_definition_id': 'test:aid', 'target_ids': (aid,),
        'metadata': {'useful_recovery': [] if recipient == 'empty' else [{'target_id': aid, 'healing_hp': 10, 'temporary_hp': 0}]}})
    ctx = ctx.model_copy(update={'actors': actors, 'policy': policy})
    from combat.gate4_controller import LocalDeterministicController
    assert component(LocalDeterministicController()._score_candidate(ctx, row, ()), 'ally_support') == 0
