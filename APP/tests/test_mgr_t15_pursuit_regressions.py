"""Regressions for review findings on Pursuit Without Horizon (MGR-T15 close-pursuit).

Each test fails on the pre-fix code: the transient engine attribute and the cell:x,y option ids.
"""
from combat.ext.sky_treading import PURSUIT_TARGET_FLAG

from test_mgr_t15_pursuit_horizon import FOE, OWNER, at, fight, move, turn


def test_pursuit_grant_leaves_no_engine_attribute_or_stale_flag(tmp_path):
    # Finding 2: the chase must not rely on an ephemeral engine attribute (_sky_pursuit_context).
    combat, table, mid = fight(tmp_path)
    turn(table, mid, FOE)

    def pick(prompt, options):
        if prompt['context']['reaction_source_id'] == 'choice:needle.pursuit_without_horizon':
            return at(options, 3, 6)
        return ((prompt.get('choice') or {}).get('preferred') or [options[0]['id']])[0]

    engine, _ = move(tmp_path, mid, 8, pick=pick)
    assert not hasattr(engine, '_sky_pursuit_context')
    assert PURSUIT_TARGET_FLAG not in engine.state.actors[OWNER].turn_flags


def test_pursuit_options_expose_no_cell_coordinates(tmp_path):
    # Finding 3: choice option ids must be opaque; the destination belongs in the label only.
    combat, table, mid = fight(tmp_path)
    turn(table, mid, FOE)
    seen = []

    def pick(prompt, options):
        if prompt['context']['reaction_source_id'] == 'choice:needle.pursuit_without_horizon':
            seen.extend(option['id'] for option in options)
            return at(options, 3, 6)
        return ((prompt.get('choice') or {}).get('preferred') or [options[0]['id']])[0]

    move(tmp_path, mid, 8, pick=pick)
    assert seen
    assert not any(option_id.startswith('cell:') or ',' in option_id for option_id in seen)
