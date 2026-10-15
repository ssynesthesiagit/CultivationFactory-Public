"""Actual sensory Search and automatic recipient choices without model servers."""
import pytest
from combat import ext
from combat.ext import sound_echoes as E, air_lifts as A
from tests import worker2_support as S
from tests.cw2_service_support import add_action, seal


@pytest.fixture(autouse=True)
def scenes(monkeypatch):
    def hidden_owner(ctx, row):
        ctx.engine._apply_condition(ctx.actor, 'condition:typed.hidden', ctx.source, ctx.actor.entity_id,
            expires_on='UNTIL_REMOVED', data={'stealth_total': 100, 'support_causes': ['unknown']})
    monkeypatch.setitem(ext._EFFECTS, 'test_mgr_t16_hide_owner', hidden_owner)


def owner_first(bundles):
    bundles[0]['actor_template']['initiative_bonus'] = 100
    seal(bundles[0])


@pytest.mark.parametrize('sense,mode', [('sight', 'NORMAL'), ('hearing', 'DISADVANTAGE')])
def test_native_search_only_qualified_field_penalty(tmp_path, sense, mode):
    def transform(bundles):
        add_action(bundles[0], 'Conceal caster', [{'type': 'test_mgr_t16_hide_owner'}], target='SELF')
    c, t, mid = S.fixture(tmp_path, [E.FIELD], dc=100, bundle_transform=transform,
                         battlefield_transform=lambda arena: arena.update(terrain_regions=[]))
    S.settle(t, mid, S.candidate(c, mid, 'Ten-Thousand Echoes Field').candidate_id)
    S.settle(t, mid, S.candidate(c, mid, 'Conceal caster').candidate_id)
    S.turn(t, mid, S.FOE)
    prompts = S.settle(t, mid, S.candidate(c, mid, 'Search').candidate_id,
        picks={'choice:needle.echo_search_sense': sense})
    assert any(p['context']['reaction_source_id'] == 'choice:needle.echo_search_sense' for p in prompts)
    e = S.reload(tmp_path, mid)
    rolls = [e for e in e.events if e.event_type == 'CHECK_ROLLED' and e.actor_id == S.FOE and e.payload.get('actor')]
    assert rolls[-1].payload['actor']['mode'] == mode


def test_automatic_updraft_recipient_resists_without_player_prompt(tmp_path):
    c, t, mid = S.fixture(tmp_path, [A.UPDRAFT], dc=100,
        bundle_transform=owner_first,
        modes={S.OWNER: 'MANUAL', S.ALLY: 'MANUAL', S.FOE: 'LOCAL_AUTO'})
    S.settle(t, mid, S.candidate(c, mid, 'Updraft Gate', at=(6, 6)).candidate_id)
    prompts = []
    for _ in range(4):
        if t.state(mid)['menu']['actor_id'] == S.FOE:
            break
        prompts += S.settle(t, mid, t.state(mid)['menu']['end_turn'])
    e = S.reload(tmp_path, mid)
    assert e.state.actors[S.FOE].position.z == 2
    assert not any(p['context']['reaction_source_id'] == 'choice:needle.updraft_consent'
                   and S.FOE in str(p['context']) for p in prompts)


def test_automatic_echo_failure_keeps_real_holder_expiry(tmp_path):
    c, t, mid = S.fixture(tmp_path, [E.FIELD], dc=100,
        bundle_transform=owner_first,
        modes={S.OWNER: 'MANUAL', S.ALLY: 'MANUAL', S.FOE: 'LOCAL_AUTO'})
    S.settle(t, mid, S.candidate(c, mid, 'Ten-Thousand Echoes Field').candidate_id)
    for _ in range(4):
        if t.state(mid)['menu']['actor_id'] == S.FOE:
            break
        S.settle(t, mid, t.state(mid)['menu']['end_turn'])
    e = S.reload(tmp_path, mid)
    actor = e.state.actors[S.FOE]
    condition = next(q for q in actor.conditions.values() if q.condition_id in ('condition:typed.reaction_denied', E.CONFUSED))
    assert S.FOE in condition.expires_on and not actor.reaction_available
