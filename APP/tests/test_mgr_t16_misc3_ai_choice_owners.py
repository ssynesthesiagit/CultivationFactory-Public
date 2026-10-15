"""Manual off-turn choices must pause a real automatic table action."""
import pytest

from combat import zones
from combat.ext.tabik_dark import CLEARSIGHT_PERMISSION
from combat.gate4_adapters import ManualControllerAdapter
from tests.h1_support import sheet
from tests.test_mgr_t16_talents_misc_3 import CHAOS, setup_actions
from tests.worker2_support import OWNER, ALLY, FOE, fixture, candidate, reload, settle, turn

CLEAR = 'TAL_DARK_CLEARSIGHT'
PURE = 'TAL_DARK_PURE_DARKNESS'


def automatic_action(combat, mid, actor, chosen, monkeypatch):
    """Script only the AI's primary selection; keep the real reaction controller.

    The table still loads/probes/commits the real LOCAL_AUTO turn. Selection
    uses the actor's observed menu and never calls a model or embedding server.
    """
    def select(context):
        picked = next(c for c in context.legal_candidates
                      if c.source_definition_id == chosen.source_definition_id
                      and c.target_ids == chosen.target_ids
                      and c.destination == chosen.destination)
        return picked.candidate_id, ()
    adapter = ManualControllerAdapter(select)
    monkeypatch.setattr(combat.controller, 'choose_primary_action', adapter.choose_primary_action)
    combat.set_controller_mode(mid, actor_id=actor, controller_mode='LOCAL_AUTO')


@pytest.mark.parametrize('accept', [False, True])
def test_ai_attacker_waits_for_manual_chaos_step_defender(tmp_path, monkeypatch, accept):
    combat, table, mid = fixture(tmp_path, [], foe_sheet=sheet([CHAOS], cl=15, name='Mara'),
                                bundle_transform=setup_actions, named=True)
    turn(table, mid, FOE)
    settle(table, mid, candidate(combat, mid, 'Test mark', target=ALLY).candidate_id)
    turn(table, mid, ALLY)
    chosen = candidate(combat, mid, 'Test miss', target=FOE)
    automatic_action(combat, mid, ALLY, chosen, monkeypatch)
    before = reload(tmp_path, mid)
    result = table.auto_step(mid, 0, [])
    assert result['status'] == 'REACTION_REQUIRED', result
    prompt = result['reaction']
    assert prompt['context']['reactor_id'] == FOE
    assert prompt['context']['reaction_source_id'] == 'choice:needle.chaos_missed_step'
    assert all(word in str(prompt) for word in ('Chaos-Step Awakening', 'Test miss', 'Mara'))
    assert reload(tmp_path, mid).state.event_sequence == before.state.event_sequence
    prompts = settle(table, mid, None, auto=True,
                     picks={'choice:needle.chaos_missed_step': 'first' if accept else None})
    assert any(p['context']['reactor_id'] == FOE for p in prompts)
    after = reload(tmp_path, mid)
    assert (after.state.actors[FOE].position != before.state.actors[FOE].position) == accept
    assert bool(after.state.actors[FOE].turn_flags.get('drunken_chaos_miss_turn')) == accept
    assert any(e.event_type == 'ATTACK_ROLLED' and e.actor_id == ALLY for e in after.events)


@pytest.mark.parametrize('allow', [False, True])
def test_ai_caster_waits_for_manual_allied_darkness_creator(tmp_path, monkeypatch, allow):
    def independent_darkness(bundles):
        for bundle in bundles:
            for action in bundle['action_catalog']:
                if action['display_name'] == 'Darkness':
                    action['concentration'] = False
                    action['parameters']['typed']['duration']['concentration'] = False
    combat, table, mid = fixture(tmp_path, [CLEAR, PURE], ally_talents=[PURE],
                                bundle_transform=independent_darkness, named=True)
    turn(table, mid, ALLY)
    settle(table, mid, candidate(combat, mid, 'Shape Darkness: Pure Darkness').candidate_id)
    settle(table, mid, candidate(combat, mid, 'Darkness', at=(3, 6)).candidate_id)
    turn(table, mid, OWNER)
    chosen = candidate(combat, mid, 'Meld: Clearsight', target=OWNER)
    automatic_action(combat, mid, OWNER, chosen, monkeypatch)
    before = reload(tmp_path, mid)
    result = table.auto_step(mid, 0, [])
    assert result['status'] == 'REACTION_REQUIRED', result
    prompt = result['reaction']
    assert prompt['context']['reactor_id'] == ALLY
    assert prompt['context']['reaction_source_id'] == 'choice:needle.clearsight_creator_consent'
    assert all(word in str(prompt) for word in ('Clearsight', 'Wren', 'Tobin'))
    assert reload(tmp_path, mid).state.event_sequence == before.state.event_sequence
    settle(table, mid, None, auto=True,
           picks={'choice:needle.clearsight_creator_consent': 'allow' if allow else None})
    after = reload(tmp_path, mid)
    holder = after.state.actors[OWNER]
    permissions = [c for c in holder.conditions.values() if c.condition_id == CLEARSIGHT_PERMISSION]
    assert bool(permissions) == allow
    if allow:
        assert permissions[0].source_actor_id == ALLY
        assert permissions[0].data['meld_instance'] in holder.conditions
    area = next(z for z in zones.typed_zones(after) if z.owner_id == ALLY)
    assert zones.clear_sighted(after, area, holder) == allow
    assert not zones.clear_sighted(after, area, after.state.actors[FOE])


@pytest.mark.parametrize('has_caster', [False, True])
def test_choice_enrollment_excludes_unowned_abilities_and_hostile_creators(tmp_path, has_caster):
    from combat.ext.drunken_style import chaos_step_choice_owners
    from combat.ext.tabik_dark import clearsight_choice_owners
    combat, table, mid = fixture(tmp_path, [CLEAR] if has_caster else [],
                                ally_talents=[PURE], foe_sheet=sheet([PURE], cl=15))
    engine = reload(tmp_path, mid)
    assert chaos_step_choice_owners(engine) == ()
    assert set(clearsight_choice_owners(engine)) == ({ALLY} if has_caster else set())
