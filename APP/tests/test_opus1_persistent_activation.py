"""F5: exact-activation limits and any-creature choices at the table, with cold reloads.

Only the dice are fixed: initial saves pass and a forced reroll fails. Native
save delivery, repeated saves, consent, payment, turns and persistence are real.
"""
import pytest

from combat.gate2_rolls import DeterministicRollAuthority
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from combat.ext import insight_rewrites as ir
from tests.h1_support import ROOT
from tests.test_opus1_insight_rewrites import _frightened, _rewrites, seal
from tests.worker2_support import ALLY, FOE, OWNER, candidate, fixture, prompt_turn, reload, settle


def _fixed_saves(monkeypatch):
    raw, d20 = DeterministicRollAuthority.raw_d20, DeterministicRollAuthority.d20

    def low(self, **kw):
        roll = raw(self, **kw)
        if kw['reason'].startswith('SAVE:action:test.opus1.'):
            roll = roll.model_copy(update={'dice': (1,), 'natural_result': 1,
                                          'total': 1 + roll.modifier, 'discarded': ()})
        return roll

    def initial(self, **kw):
        if not kw['reason'].startswith('SAVE:action:test.opus1.'):
            return d20(self, **kw)
        roll = self.raw_d20(**kw)
        roll = roll.model_copy(update={'dice': (20,), 'natural_result': 20, 'total': 20 + roll.modifier})
        return self.after_d20(roll) if self.after_d20 else roll

    monkeypatch.setattr(DeterministicRollAuthority, 'raw_d20', low)
    monkeypatch.setattr(DeterministicRollAuthority, 'd20', initial)


def _setup(bundles):
    seal(bundles[0], 'Continuing Fear', [{'type': 'save', 'ability': 'wis', 'on_success': [],
         'on_fail': [{'type': 'condition', 'condition': 'frightened', 'applies_to': 'target',
                      'until_escape': True, 'repeat_save': {'ability': 'WIS', 'when': 'end'}}]}],
         save_dc=10, sphere='tianxia.sphere.test')


def _cold(tmp_path):
    combat = CombatService(ROOT, tmp_path)
    return combat, TabletopService(combat, tmp_path)


def _asked(prompts):
    return [p for p in prompts if p['context']['reaction_source_id'] == 'reaction:typed.' + ir.PERSISTENT]


@pytest.mark.parametrize('ask', [True, False], ids=['ask-owner', 'automatic-owner'])
def test_one_activation_cannot_be_used_again_on_its_native_repeat_after_reload(tmp_path, monkeypatch, ask):
    _fixed_saves(monkeypatch)
    combat, table, mid = fixture(tmp_path, [], owner_insights=[ir.PERSISTENT], ask=ask,
                                 bundle_transform=_setup)
    qi = reload(tmp_path, mid).state.actors[OWNER].resources['resource:core.qi']
    prompts = settle(table, mid, candidate(combat, mid, 'Continuing Fear', target=FOE).candidate_id,
                     picks={'reaction:typed.' + ir.PERSISTENT: 'USE'})
    assert bool(_asked(prompts)) == ask
    engine = reload(tmp_path, mid)
    condition = next(c for c in engine.state.actors[FOE].conditions.values()
                     if c.condition_id == 'condition:typed.frightened')
    identity = condition.data['save_activation_id']
    assert isinstance(identity, str)
    assert len(_rewrites(engine, ir.PERSISTENT)) == 1
    combat, table = _cold(tmp_path)
    prompt_turn(table, mid, FOE)
    # Turn use has refreshed. This is still the original cast's native repeat.
    prompts = settle(table, mid, table.state(mid)['menu']['end_turn'],
                     picks={'reaction:typed.' + ir.PERSISTENT: 'USE'})
    assert not _asked(prompts)
    engine = reload(tmp_path, mid)
    assert not _frightened(engine.state.actors[FOE])
    assert len(_rewrites(engine, ir.PERSISTENT)) == 1
    assert engine.state.actors[OWNER].resources['resource:core.qi'] == qi - 3
    # A genuine new activation of the SAME action remains eligible.
    combat, table = _cold(tmp_path)
    prompt_turn(table, mid, OWNER)
    prompts = settle(table, mid, candidate(combat, mid, 'Continuing Fear', target=FOE).candidate_id,
                     picks={'reaction:typed.' + ir.PERSISTENT: 'USE'})
    assert bool(_asked(prompts)) == ask
    engine = reload(tmp_path, mid)
    assert len(_rewrites(engine, ir.PERSISTENT)) == 2
    assert engine.state.actors[OWNER].resources['resource:core.qi'] == qi - 6
    condition = next(c for c in engine.state.actors[FOE].conditions.values()
                     if c.condition_id == 'condition:typed.frightened')
    assert condition.data['save_activation_id'] != identity


@pytest.mark.parametrize('target', [ALLY, OWNER], ids=['ally', 'self'])
@pytest.mark.parametrize('accept', [False, True], ids=['decline', 'accept'])
def test_any_creature_save_offers_player_choice_and_persists_payment(tmp_path, monkeypatch, target, accept):
    _fixed_saves(monkeypatch)
    combat, table, mid = fixture(tmp_path, [], owner_insights=[ir.PERSISTENT], bundle_transform=_setup,
                                 named=True)
    engine = reload(tmp_path, mid)
    qi = engine.state.actors[OWNER].resources['resource:core.qi']
    name = engine.state.actors[target].display_name
    prompts = settle(table, mid, candidate(combat, mid, 'Continuing Fear', target=target).candidate_id,
                     picks={'reaction:typed.' + ir.PERSISTENT: 'USE' if accept else None})
    asked = _asked(prompts)
    assert len(asked) == 1
    assert asked[0]['context']['reactor_id'] == OWNER
    assert 'Persistent Technique' in str(asked) and 'Continuing Fear' in str(asked) and name in str(asked)
    engine = reload(tmp_path, mid)
    assert len(_rewrites(engine, ir.PERSISTENT)) == int(accept)
    assert engine.state.actors[OWNER].resources['resource:core.qi'] == qi - 3 * int(accept)
    assert _frightened(engine.state.actors[target]) == accept
    flags = [k for k in engine.state.actors[OWNER].turn_flags if 'persistent_technique:activation:' in k]
    assert bool(flags) == accept


def test_automatic_owner_preserves_friendly_success_without_payment(tmp_path, monkeypatch):
    _fixed_saves(monkeypatch)
    combat, table, mid = fixture(tmp_path, [], owner_insights=[ir.PERSISTENT], ask=False,
                                 bundle_transform=_setup)
    qi = reload(tmp_path, mid).state.actors[OWNER].resources['resource:core.qi']
    assert not _asked(settle(table, mid, candidate(combat, mid, 'Continuing Fear', target=ALLY).candidate_id))
    engine = reload(tmp_path, mid)
    assert not _rewrites(engine, ir.PERSISTENT)
    assert engine.state.actors[OWNER].resources['resource:core.qi'] == qi
