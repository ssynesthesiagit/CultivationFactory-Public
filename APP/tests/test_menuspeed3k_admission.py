"""Unforced local decisions must respect exhaustive placement admission."""
import pytest

from combat import placement_menu
from combat.ext import needle
from tests.test_menuspeed3_review import offline_menu_embeddings, payload
from tests.worker2_support import OWNER, ALLY, FOE, fixture, reload, settle


def empty_fireball(tmp_path, monkeypatch):
    monkeypatch.setenv('CF_COMBAT_AI_SLICES_1_2', '1')
    def arena(document):
        document['width_squares'] = 70
    def stationary(bundles):
        from combat.canonical import canonical_sha256
        bundle = bundles[0]
        bundle['actor_template']['speed_ft'] = 0
        bundle.pop('bundle_sha256', None)
        bundle['bundle_sha256'] = canonical_sha256(bundle)
    combat, table, mid = fixture(tmp_path, ['FIRE_TAL_FIREBALL_ART'], owner_speed=0,
        positions={OWNER: {'x': 3, 'y': 6}, ALLY: {'x': 2, 'y': 6},
                   FOE: {'x': 65, 'y': 6}}, battlefield_transform=arena,
        bundle_transform=stationary)
    session = combat._load_session(mid)
    root = next(c for c in combat._legal_candidates(session)
                if c.metadata.get('placement_picker') and c.display_name.startswith('Fireball Art —'))
    rows = list(placement_menu.cells(session.engine, root))
    assert len(rows) > 1 and all(c.metadata.get('empty_area') for c in rows)
    assert session.engine.action_catalog[root.source_definition_id].parameters['expected_damage'] > 0
    return combat, table, mid, root, rows


def test_unforced_local_auto_does_not_spend_empty_damaging_area(tmp_path, monkeypatch):
    combat, table, mid, root, rows = empty_fireball(tmp_path, monkeypatch)
    combat.set_controller_mode(mid, actor_id=OWNER, controller_mode='LOCAL_AUTO')
    context = combat.ai_decision_context(combat._load_session(mid))
    assert any(c.candidate_id == root.candidate_id for c in context.legal_candidates)
    engine = combat._load_session(mid).engine
    assert placement_menu.search(engine, root, context) is None
    ai_root = next(c for c in context.legal_candidates if c.candidate_id == root.candidate_id)
    from combat.gate4_controller import _deals_damage
    assert not _deals_damage(ai_root)
    assert combat.controller._score_candidate(context, ai_root, ()).total < 0
    choice = combat.controller.choose_primary_action(context)
    chosen = next(c for c in context.legal_candidates if c.candidate_id == choice.intent.candidate_id)
    before_cp = engine.state.actors[OWNER].resources.copy()
    # Use the actual controller and service transport, without forcing an intent,
    # replacing search, or intercepting the square checkpoint.
    result = table.auto_step(mid, 0, [])
    assert result['status'] == 'COMMITTED', result
    fresh = reload(tmp_path, mid)
    assert fresh.state.actors[OWNER].resources == before_cp
    assert chosen.source_definition_id != root.source_definition_id
    assert not any(e.source_definition_id == root.source_definition_id for e in fresh.events)


def test_unanswered_auto_picker_cannot_default_to_an_unadmitted_square(tmp_path, monkeypatch):
    combat, _, mid, root, rows = empty_fireball(tmp_path, monkeypatch)
    combat.set_controller_mode(mid, actor_id=OWNER, controller_mode='LOCAL_AUTO')
    before = combat._load_session(mid).engine.state.model_dump(mode='json')
    # A root submitted without an aim must not spend its first legal square
    # when the default controller has no recommendation. Explicit aims remain
    # valid; rejection occurs before action/resource payment.
    with pytest.raises(Exception) as refused:
        # Exercise the shared commit path directly: the owner submit endpoint
        # correctly refuses any submission for a LOCAL_AUTO seat.
        combat._commit_previewed(mid, payload(root), [], None)
    assert 'Choose a legal square' in str(refused.value) or 'rejected' in str(refused.value)
    assert combat._load_session(mid).engine.state.model_dump(mode='json') == before
    combat._commit_previewed(mid, payload(root, rows[-1].destination), [], None)
    assert reload(tmp_path, mid).state.actors[OWNER].resources != before['actors'][OWNER]['resources']


@pytest.mark.parametrize('seat', ['MANUAL', 'MODEL'])
def test_empty_area_keeps_every_human_and_model_square(tmp_path, monkeypatch, seat):
    combat, table, mid, root, rows = empty_fireball(tmp_path, monkeypatch)
    aimed = rows[-1].destination
    if seat == 'MANUAL':
        prompts = settle(table, mid, root.candidate_id,
            picks={placement_menu.CHOICE: needle.cell_id(aimed, include_altitude=True)})
        prompt = next(p for p in prompts if p['context']['reaction_source_id'] == placement_menu.CHOICE)
        assert {o['id'] for o in prompt['choice']['options']} == {
            needle.cell_id(c.destination, include_altitude=True) for c in rows}
    else:
        import json
        from tests.test_agent_seats import runner_for
        seen = []
        def fake(provider, prompt, png):
            frame = json.loads(prompt.split('\n', 1)[1])
            legal = frame['legal_menu']
            if 'ability' in legal:
                options = legal['choice']['options']
                assert len(options) == len(rows)
                seen.append(options[-1]['id'])
                return json.dumps({'selection': 'USE', 'option_ids': seen[-1:], 'spend': 0}), {}
            key = next((k for k, r in legal.items() if r['action'] == 'Fireball Art'), None)
            if key is None:
                return 'MORE', {}
            end = next(k for k, r in legal.items() if r['action'] == 'End turn')
            return json.dumps({'plan': [key, end]}), {}
        runner, _ = runner_for(tmp_path, table, fake, timeout=30)
        runner.set_seat(mid, OWNER, 'MODEL', 'fake')
        assert runner.drive(mid, max_steps=1) == 1
        assert runner.drive(mid, max_steps=1) == 1
        assert seen and all(not r.get('fallback') for r in runner.decisions(mid))
    fresh = reload(tmp_path, mid)
    assert any(e.source_definition_id == root.source_definition_id for e in fresh.events)
