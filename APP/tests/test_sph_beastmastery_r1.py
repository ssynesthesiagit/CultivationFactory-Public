"""Pack review regressions: transactions, then fresh service replay/reload.

Synthetic actions only create a triggering roll/condition; they never replace a
production ability. No GUI or browser is launched by this module.
"""
import pytest

from combat.ext import beastmastery_pack as pack
from tests.cw2_service_support import add_action, seal
from tests.worker2_support import OWNER, ALLY, FOE, fixture, candidate, settle, turn, reload

MIND = 'TAL_BEASTMASTERY_SOVEREIGN_PACK_MIND'
PROCESSION = 'TAL_BEASTMASTERY_TEN_THOUSAND_BEAST_PROCESSION'
ENCIRCLE = 'TAL_BEASTMASTERY_PACK_ENCIRCLEMENT'
TAMER = 'TAL_BEASTMASTERY_BEAST_TAMER'
CHOICE = 'choice:needle.beastmastery.pack_mind'
ACTIVE = 'condition:typed.sovereign_pack_mind'


def setup(tmp_path, talents=(MIND,), *, ask=True, modes=None, beast_count=1):
    def prepare(bundles):
        # Two independent rolls can be committed in one turn without resetting receipts.
        for beast in bundles[0]['summons']:
            for name in ('First check', 'Second check'):
                add_action(beast, name, [{'type': 'contest_against', 'applies_to': 'target',
                           'actor_check': {'kind': 'check', 'ability': 'WIS', 'skill': 'Perception'},
                           'target_check': {'kind': 'dc', 'dc': 16}}])
            seal(beast)
        for bundle in bundles:
            add_action(bundle, 'Fear test', [{'type': 'condition', 'condition': 'frightened',
                       'applies_to': 'target', 'duration': 'until_start_of_next_turn'}])
            add_action(bundle, 'Save test', [{'type': 'save', 'ability': 'WIS', 'dc': 16,
                       'applies_to': 'target', 'on_fail': [], 'on_success': []}])
            if bundle['actor_id'] == FOE:
                bundle['action_catalog'][-1]['parameters'].pop('player_only', None)
                seal(bundle)
    return fixture(tmp_path, [TAMER, *talents], ask=ask, modes=modes,
                   owner_plan={'beasts': ['wolf'] * beast_count, 'mount': ''},
                   bundle_transform=prepare, seed='SPH-BEAST-R1', foe_position={'x': 3, 'y': 4})


def beasts(tmp_path, mid):
    e = reload(tmp_path, mid)
    return [a.entity_id for a in pack.beast_allies(e, e.state.actors[OWNER])]


def use(combat, table, mid, name, *, target=None, accept=True):
    return settle(table, mid, candidate(combat, mid, name, target=target).candidate_id,
                  {CHOICE: 'grant' if accept else None})


def grants(engine):
    return [e for e in engine.events if e.event_type == 'D20_REWRITTEN'
            and e.source_definition_id == MIND]


def test_owning_pack_mind_does_not_activate_it(tmp_path):
    combat, table, mid = setup(tmp_path)
    beast = beasts(tmp_path, mid)[0]
    turn(table, mid, beast)
    use(combat, table, mid, 'First check', target=FOE)
    e = reload(tmp_path, mid)
    assert not grants(e)
    assert pack.PACK_MIND_ROUND_FLAG not in e.state.actors[OWNER].turn_flags


def test_procession_does_not_invent_fear_immunity(tmp_path):
    combat, table, mid = setup(tmp_path, (PROCESSION,))
    beast = beasts(tmp_path, mid)[0]
    use(combat, table, mid, 'Fear test', target=beast)
    e = reload(tmp_path, mid)
    assert any(c.condition_id.endswith('.frightened') for c in e.state.actors[beast].conditions.values())


def test_encirclement_keeps_scoped_disengage_manual(tmp_path):
    combat, table, mid = setup(tmp_path, (ENCIRCLE,), beast_count=2)
    turn(table, mid, FOE)
    e = reload(tmp_path, mid)
    assert len([b for b in pack.beast_allies(e, e.state.actors[OWNER])
                if e._distance_actor_to_actor(b, e.state.actors[FOE]) <= 5]) >= 2
    use(combat, table, mid, 'Disengage')
    assert reload(tmp_path, mid).state.actors[FOE].turn_flags['disengaged']


def test_paid_activation_decline_accept_receipt_and_next_round(tmp_path):
    combat, table, mid = setup(tmp_path)
    use(combat, table, mid, 'Sovereign Pack Mind')
    e = reload(tmp_path, mid)
    assert e.state.actors[OWNER].resources['resource:core.martial_focus'] == 0
    assert any(c.condition_id == ACTIVE for c in e.state.actors[OWNER].conditions.values())
    beast = beasts(tmp_path, mid)[0]
    turn(table, mid, beast)
    prompts = use(combat, table, mid, 'First check', target=FOE, accept=False)
    assert any(p['context']['reaction_source_id'] == CHOICE for p in prompts)
    assert not grants(reload(tmp_path, mid))
    prompts = use(combat, table, mid, 'Second check', target=FOE)
    p = next(p for p in prompts if p['context']['reaction_source_id'] == CHOICE)
    assert 'Sovereign Pack Mind' in str(p) and 'Second check' in str(p)
    e = reload(tmp_path, mid)
    assert len(grants(e)) == 1
    assert grants(e)[0].payload['bonus'] == e.state.actors[OWNER].proficiency_bonus
    original, effective = (grants(e)[0].payload[key] for key in ('original', 'result'))
    assert effective['total'] == original['total'] + e.state.actors[OWNER].proficiency_bonus
    assert effective['natural_result'] == original['natural_result']
    assert effective['mode'] == original['mode']
    assert e.state.actors[OWNER].turn_flags[pack.PACK_MIND_ROUND_FLAG] == e.state.round_number
    use(combat, table, mid, 'First check', target=FOE)
    assert len(grants(reload(tmp_path, mid))) == 1
    turn(table, mid, OWNER)
    turn(table, mid, beast)
    use(combat, table, mid, 'First check', target=FOE)
    assert len(grants(reload(tmp_path, mid))) == 2


@pytest.mark.parametrize('kind', ['Bite', 'Save test'])
def test_manual_owner_is_asked_on_other_turns(tmp_path, kind):
    combat, table, mid = setup(tmp_path)
    use(combat, table, mid, 'Sovereign Pack Mind')
    beast = beasts(tmp_path, mid)[0]
    turn(table, mid, beast if kind == 'Bite' else FOE)
    prompts = use(combat, table, mid, kind, target=FOE if kind == 'Bite' else beast)
    assert any(p['context']['reactor_id'] == OWNER and p['context']['reaction_source_id'] == CHOICE for p in prompts)
    assert len(grants(reload(tmp_path, mid))) == 1


@pytest.mark.parametrize('accept', [False, True])
def test_manual_owner_asked_on_ai_turn_and_preview_is_inert(tmp_path, accept):
    from combat.gate4_adapters import ManualControllerAdapter
    combat, table, mid = setup(tmp_path)
    use(combat, table, mid, 'Sovereign Pack Mind')
    beast = beasts(tmp_path, mid)[0]
    turn(table, mid, FOE)
    source = candidate(combat, mid, 'Save test', target=beast).source_definition_id
    real = combat.controller

    class ScriptedController:
        def choose_primary_action(self, context):
            cid = next(c.candidate_id for c in context.legal_candidates
                       if c.source_definition_id == source and c.target_ids == (beast,))
            return ManualControllerAdapter(lambda _: (cid, ())).choose_primary_action(context)

        def __getattr__(self, name):
            return getattr(real, name)

    # Controller injection selects a real candidate, without replacing any engine function.
    combat.controller = ScriptedController()
    combat.set_controller_mode(mid, actor_id=FOE, controller_mode='LOCAL_AUTO')
    before = reload(tmp_path, mid).state.model_dump(mode='json')
    result = table.auto_step(mid, 0)
    assert result['status'] == 'REACTION_REQUIRED'
    p = result['reaction']
    assert p['context']['reactor_id'] == OWNER
    assert p['context']['reaction_source_id'] == CHOICE
    assert reload(tmp_path, mid).state.model_dump(mode='json') == before
    assert table.auto_step(mid, 0)['reaction'] == p
    answer = {**p['context'], 'selection': 'USE' if accept else 'DECLINE'}
    if accept:
        answer['option_ids'] = ['grant']
    assert table.auto_step(mid, 0, [answer])['status'] == 'COMMITTED'
    e = reload(tmp_path, mid)
    assert len(grants(e)) == int(accept)
    assert (pack.PACK_MIND_ROUND_FLAG in e.state.actors[OWNER].turn_flags) == accept


@pytest.mark.parametrize('ai_owner', [False, True])
def test_manual_choices_and_ai_owners_use_existing_transport(tmp_path, ai_owner):
    combat, table, mid = setup(tmp_path, ask=ai_owner)
    use(combat, table, mid, 'Sovereign Pack Mind')
    beast = beasts(tmp_path, mid)[0]
    turn(table, mid, FOE)
    if ai_owner:
        combat.set_controller_mode(mid, actor_id=OWNER, controller_mode='LOCAL_AUTO')
    prompts = use(combat, table, mid, 'Save test', target=beast)
    assert any(p['context']['reaction_source_id'] == CHOICE for p in prompts) == (not ai_owner)
    assert len(grants(reload(tmp_path, mid))) == 1


def test_pack_mind_expires_after_one_minute(tmp_path):
    combat, table, mid = setup(tmp_path)
    use(combat, table, mid, 'Sovereign Pack Mind')
    for _ in range(10):
        turn(table, mid, beasts(tmp_path, mid)[0])
        turn(table, mid, OWNER)
    e = reload(tmp_path, mid)
    assert not any(c.condition_id == ACTIVE for c in e.state.actors[OWNER].conditions.values())
    turn(table, mid, beasts(tmp_path, mid)[0])
    use(combat, table, mid, 'First check', target=FOE)
    assert not grants(reload(tmp_path, mid))
