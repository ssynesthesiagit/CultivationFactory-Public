"""Real lazy SUGGESTED menus consumed by both clients, with no live models."""
import json
from pathlib import Path
import subprocess
from types import SimpleNamespace

import pytest

from combat import embedding_rank, menu_rank
from tests.worker2_support import fixture, OWNER, FOE, ALLY


@pytest.fixture
def offered(tmp_path, monkeypatch):
    monkeypatch.setenv('CF_EMBED_MENU', '1')
    monkeypatch.setattr(menu_rank, '_CLIENT', embedding_rank.EmbeddingClient(
        transport=lambda *a: (_ for _ in ()).throw(OSError('offline fake'))))
    combat, table, mid = fixture(tmp_path, [], ask=False, seed='MENUSPEED7F2',
        foe_position={'x': 3, 'y': 5}, modes={OWNER: 'SUGGESTED', FOE: 'MANUAL', ALLY: 'MANUAL'})
    # Ranking the first layer must not secretly enumerate the native AI menu.
    monkeypatch.setattr(menu_rank, 'native_scores', lambda *a, **kw: pytest.fail('eager ranking'))
    ranked_ids = []
    original_rank = menu_rank.rank_ids
    def observe_rank(*args, **kwargs):
        ids = original_rank(*args, **kwargs)
        ranked_ids.extend(ids)
        return ids
    monkeypatch.setattr(menu_rank, 'rank_ids', observe_rank)
    state = table.state(mid, lazy=True, fog=True, fog_view='own', fog_actor_ids=(OWNER,))
    menu = state['menu']
    assert menu['control_mode'] == 'SUGGESTED' and menu['lazy'] and menu['movement_grid']
    assert not menu['moves']
    # Select a real weapon/unarmed attack, not a synthetic menu group.
    engine = combat._load_session(mid).engine
    sources = {g['source_definition_id'] for g in menu['actions'] if g.get('lazy')}
    source = next(c.source_definition_id for c in engine.legal_candidates()
                  if c.source_definition_id in sources and FOE in c.target_ids
                  and ('.weapon.' in c.source_definition_id or 'unarmed' in c.source_definition_id))
    expansion = table.expand_action(mid, source, menu['decision_id'], menu['state_version'])
    assert any(FOE in o['target_ids'] for g in expansion['actions'] for o in g['options'])
    x, y, z, _, mode, _ = menu['movement_grid'][0]
    quote = table.preview_destination(mid, menu['decision_id'], menu['state_version'], OWNER,
                                     {'x': x, 'y': y, 'z': z}, mode)
    return dict(state=state, source=source, expansion=expansion, quote=quote, all_ranked=ranked_ids)


def test_lazy_assisted_ranks_sources_and_compact_movement(offered):
    menu = offered['state']['menu']
    headers = {f"source:{g['source_definition_id']}" for g in menu['actions'] if g.get('lazy')}
    ranked = {key for ids in menu['ranked_slots'].values() for key in ids}
    assert headers & ranked, 'Assisted must consider lazy sources before manual expansion'
    # Header hashes vary with the match identity. Inspect the complete ranking,
    # not whether this particular attack happens to land in the first five.
    assert 'source:' + offered['source'] in offered['all_ranked']
    assert menu['ranked_slots']['Movement'] == ['movement:compact']
    assert all(not g['options'] for g in menu['actions'] if g.get('lazy'))


def test_real_lazy_assisted_desktop_and_phone_confirmation(offered):
    app = Path(__file__).resolve().parents[1]
    result = subprocess.run(['node', 'tests/menuspeed7_assisted.mjs'], cwd=app,
        input=json.dumps(offered), capture_output=True, text=True, timeout=45)
    assert result.returncode == 0, result.stdout + result.stderr


def test_lazy_source_ranking_uses_only_perceived_prose(monkeypatch):
    monkeypatch.setenv('CF_EMBED_MENU', '1')
    seen = []
    def rank(query, rows, **kwargs):
        seen.extend(text for _, text, _ in rows)
        return [key for key, _, _ in rows]
    monkeypatch.setattr(menu_rank, 'rank_ids', rank)
    engine = SimpleNamespace(state=SimpleNamespace(initiative_order=(), actors={
        'me': SimpleNamespace(current_hp=20, maximum_hp=20),
        'actor:secret': SimpleNamespace(display_name='Hidden spy')}))
    menu = {'manual': True, 'actor_id': 'me', 'control_mode': 'SUGGESTED',
            'actions': [{'source_definition_id': 'attack', 'economy': 'ACTION',
                         'lazy': True, 'label': 'Strike Hidden spy',
                         'description': 'Target actor:secret', 'options': []}]}
    menu_rank.rank_menu(menu, engine, known={'me'})
    assert seen and all('Hidden spy' not in text and 'actor:secret' not in text for text in seen)
    assert menu['ranked_slots']['Action'] == ['source:attack']
