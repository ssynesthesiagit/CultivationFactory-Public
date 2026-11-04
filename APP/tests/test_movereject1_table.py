"""Movement quotes survive real table commits and cold reloads."""
import random

import pytest

from combat.factory_compiler import compile_character
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from tests.h1_support import ROOT, sheet

OWNER, ENEMY = 'actor:factory.move-owner', 'actor:factory.move-enemy'


def commit(table, mid, cid, move=None):
    state = table.state(mid)
    menu = state['menu']
    answers = []
    for _ in range(20):
        if move is None:
            result = table.act(mid, cid, menu['decision_id'], menu['state_version'], 0, answers)
        else:
            result = table.commit_move_path(mid, cid, menu['decision_id'], menu['state_version'],
                menu['actor_id'], move['path'], 0, move.get('movement_mode', 'walk'), answers)
        if result['status'] == 'COMMITTED':
            return result
        assert result['status'] == 'REACTION_REQUIRED', result
        answers.append({**result['reaction']['context'], 'selection': 'DECLINE', 'option_ids': []})
    pytest.fail('too many reaction prompts')


@pytest.mark.parametrize('kind', ['walk', 'fly', 'summon'])
@pytest.mark.parametrize('submission', ['candidate', 'waypoints'])
def test_menu_move_commit_reload(tmp_path, kind, submission):
    combat = CombatService(ROOT, tmp_path)
    battlefield = next(v for k, v in combat.factory_arenas().items() if k.endswith('ruined-spirit-shrine'))
    talents = ['TAL_AIR_WIND_BORNE_BODY'] if kind == 'fly' else ['TAL_BEASTMASTERY_BEAST_TAMER'] if kind == 'summon' else []
    bundles = (compile_character(sheet(talents), actor_id=OWNER), compile_character(sheet([]), actor_id=ENEMY))
    session = combat.persistence.create_match(match_seed='MOVEREJECT-TABLE-'+kind, typed_bundles=bundles,
        battlefield=battlefield, roster_setup={'primary_actor_ids': [OWNER, ENEMY],
            'team_by_actor': {OWNER: 'team:a', ENEMY: 'team:b'},
            'starting_positions': {OWNER: {'x': 2, 'y': 7}, ENEMY: {'x': 17, 'y': 7}}})
    mid = session.match_id
    for who in (OWNER, ENEMY):
        combat.set_controller_mode(mid, actor_id=who, controller_mode='MANUAL')
    table = TabletopService(combat, tmp_path)
    who = OWNER
    if kind == 'summon':
        who = next(a.entity_id for a in session.engine.state.actors.values()
                   if a.summon and '.beast0.wolf.' in a.entity_id)
    for _ in range(8):
        state = table.state(mid)
        if state['menu']['actor_id'] == who:
            break
        commit(table, mid, state['menu']['end_turn'])
    assert table.state(mid)['menu']['actor_id'] == who
    if kind == 'fly':
        # Choose a concrete current placement, rather than its square-picker
        # placeholder. The table retains this exact-candidate submission API.
        current = next(c for c in combat._load_session(mid).engine.legal_candidates()
                       if 'Gather Current' in c.display_name and c.destination is not None)
        commit(table, mid, current.candidate_id)
        assert any(c.data.get('fly_speed_ft') for c in combat._load_session(mid).engine.state.actors[OWNER].conditions.values())
    state = table.state(mid)
    moves = state['menu']['moves']
    assert moves
    rng = random.Random('MOVEREJECT-'+kind)
    chosen = rng.sample(moves, min(16, len(moves)))
    match_dir = combat._load_session(mid).store.match_dir
    snapshot = {p.relative_to(match_dir): p.read_bytes() for p in match_dir.rglob('*') if p.is_file() and 'lock' not in p.name.lower()}
    for move in chosen:
        for p in match_dir.rglob('*'):
            if p.is_file() and 'lock' not in p.name.lower() and p.relative_to(match_dir) not in snapshot:
                p.unlink()
        for relative, content in snapshot.items():
            (match_dir / relative).parent.mkdir(parents=True, exist_ok=True)
            (match_dir / relative).write_bytes(content)
        combat = CombatService(ROOT, tmp_path)
        table = TabletopService(combat, tmp_path)
        try:
            result = commit(table, mid, move['candidate_id'], move if submission == 'waypoints' else None)
        except Exception as exc:
            diagnostic = getattr(exc, 'diagnostic', None)
            pytest.fail(f'{kind}: {move!r}: {getattr(diagnostic, "code", None)}; '
                        f'details={getattr(diagnostic, "details", None)!r}; {exc}')
        assert result['status'] == 'COMMITTED'
        loaded = CombatService(ROOT, tmp_path)._load_session(mid)
        assert any(e.event_type == 'MOVEMENT_COMMITTED' and e.actor_id == who for e in loaded.engine.events)
        assert loaded.mechanical.replay()['status'] == 'PASS'
