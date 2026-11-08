"""Manual off-turn choices must pause a real automatic table action."""
import pytest

from combat import zones
from combat.canonical import canonical_sha256
from combat.ext.tabik_dark import CLEARSIGHT_PERMISSION
from combat.gate4_adapters import ManualControllerAdapter
from tests.h1_support import sheet
from tests.test_mgr_t16_talents_misc_3 import CHAOS, setup_actions
from tests.worker2_support import OWNER, ALLY, FOE, fixture, candidate, reload, settle, turn, sealed_native_attack

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
    def isolate_chaos(bundles):
        setup_actions(bundles)
        attacker = next(b for b in bundles if b['actor_id'] == ALLY)
        attacker['action_catalog'] = [a for a in attacker['action_catalog']
                                      if a['source_definition_id'] != 'test:missing_attack']
        attacker['actor_template']['action_ids'].remove('test:missing_attack')
        sealed_native_attack(attacker, 'Test miss', attack_bonus=-100)
        defender = next(b for b in bundles if b['actor_id'] == FOE)
        # Prerequisites include Swaying Guard. It must neither prompt before
        # the miss nor accidentally enroll this defender for an unrelated ask.
        defender['typed_reactions'] = []
        for row in defender.get('typed_passives', []):
            row.pop('choice_owner', None)
        defender.pop('bundle_sha256', None)
        defender['bundle_sha256'] = canonical_sha256(defender)
    combat, table, mid = fixture(tmp_path, [], foe_sheet=sheet([CHAOS], cl=15, name='Mara'),
                                bundle_transform=isolate_chaos, named=True)
    turn(table, mid, FOE)
    settle(table, mid, candidate(combat, mid, 'Test mark', target=ALLY).candidate_id)
    turn(table, mid, ALLY)
    chosen = candidate(combat, mid, 'Test miss', target=FOE)
    automatic_action(combat, mid, ALLY, chosen, monkeypatch)
    before = reload(tmp_path, mid)
    from combat.ext.ability_source import compiled_feature_rows
    from combat.typed_executor import bears_mark
    from combat.gate2_rolls import DeterministicRollAuthority as Roller
    assert any(r.get('block') == 'drunken_step_benefit'
               for r in compiled_feature_rows(before, FOE, CHAOS))
    assert bears_mark(before.state.actors[ALLY], FOE, 'Off-Rhythm')
    assert FOE in before.typed_ask_reactors
    raw = Roller.raw_d20
    def miss(self, **kwargs):
        rolled = raw(self, **kwargs)
        if kwargs['actor_id'] == ALLY and kwargs['reason'].startswith('ATTACK:'):
            return rolled.model_copy(update={'natural_result': 1, 'dice': (1,), 'discarded': (),
                                              'total': 1 + kwargs['modifier']})
        return rolled
    monkeypatch.setattr(Roller, 'raw_d20', miss)
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
            bundle.pop('bundle_sha256', None)
            bundle['bundle_sha256'] = canonical_sha256(bundle)
    combat, table, mid = fixture(tmp_path, [CLEAR, PURE], ally_talents=[PURE],
                                bundle_transform=independent_darkness, named=True)
    # A fresh allied recipient is an admitted AI target. Accepting the Meld
    # and permitting immunity to the recipient's own Darkness are separate
    # decisions: accept the former explicitly before testing the latter.
    chosen = candidate(combat, mid, 'Meld: Clearsight', target=ALLY)
    ordinary_primary = combat.controller.choose_primary_action
    automatic_action(combat, mid, OWNER, chosen, monkeypatch)
    before = reload(tmp_path, mid)
    result = table.auto_step(mid, 0, [])
    assert result['status'] == 'REACTION_REQUIRED', result
    answers = []
    if result['reaction']['context']['reaction_source_id'] == 'choice:needle.dark_meld_consent':
        recipient = result['reaction']
        assert recipient['context']['reactor_id'] == ALLY
        assert reload(tmp_path, mid).state.event_sequence == before.state.event_sequence
        answer = {**recipient['context'], 'selection': 'USE', 'option_ids': ['accept']}
        answers.append(answer)
        result = table.auto_step(mid, 0, answers)
        assert result['status'] == 'REACTION_REQUIRED', result
    prompt = result['reaction']
    assert prompt['context']['reactor_id'] == ALLY
    assert prompt['context']['reaction_source_id'] == 'choice:needle.clearsight_creator_consent'
    assert all(word in str(prompt) for word in ('Clearsight', 'Wren', 'Tobin'))
    assert reload(tmp_path, mid).state.event_sequence == before.state.event_sequence
    # Resume the reserved transaction with its exact earlier answer prefix.
    # Starting settle() here would discard recipient consent already supplied.
    answer = {**prompt['context'], 'selection': 'USE' if allow else 'DECLINE'}
    if allow:
        answer['option_ids'] = ['allow']
    answers.append(answer)
    assert table.auto_step(mid, 0, answers)['status'] == 'COMMITTED'
    after = reload(tmp_path, mid)
    holder = after.state.actors[ALLY]
    permissions = [c for c in holder.conditions.values() if c.condition_id == CLEARSIGHT_PERMISSION]
    assert bool(permissions) == allow
    if allow:
        assert permissions[0].source_actor_id == ALLY
        assert permissions[0].data['meld_instance'] in holder.conditions
    combat.set_controller_mode(mid, actor_id=OWNER, controller_mode='MANUAL')
    # Later menus also ask the primary chooser for ranking. The one-action
    # script is no longer applicable once this Meld has been committed.
    monkeypatch.setattr(combat.controller, 'choose_primary_action', ordinary_primary)
    turn(table, mid, ALLY)
    settle(table, mid, candidate(combat, mid, 'Shape Darkness: Pure Darkness').candidate_id)
    settle(table, mid, candidate(combat, mid, 'Darkness', at=(3, 6)).candidate_id)
    after = reload(tmp_path, mid)
    holder = after.state.actors[ALLY]
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
