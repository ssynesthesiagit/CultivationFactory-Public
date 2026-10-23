from combat.ext.sky_treading import PURSUIT
from tests.test_mgr_t15_pursuit_horizon import fight, move, turn, OWNER, FOE


def test_p5_rows(tmp_path):
    combat, table, mid = fight(tmp_path)
    turn(table, mid, FOE)
    engine = combat._load_session(mid).engine
    raw = getattr(engine, 'typed_reaction_rows', {}).get(OWNER, [])
    desc = [(r.get('block'), r.get('kind'), str(r.get('feature_id'))[-22:], r.get('held_back'), r.get('free')) for r in raw]
    passive = [(r.get('block'), r.get('kind'), str(r.get('feature_id'))[-22:]) for r in getattr(engine, 'typed_passive_rows', {}).get(OWNER, [])]
    from combat import typed_reactions as tr
    post = [(r.get('block'), r.get('kind'), str(r.get('feature_id'))[-22:]) for r in tr._rows(engine, OWNER, 'generic')]
    feats = [str(f)[-30:] for f in getattr(engine.state.actors[OWNER], 'action_ids', [])][:0]
    owner = engine.state.actors[OWNER]
    raise AssertionError('ROWS|raw=' + str(desc)[:900] + ' ## passive=' + str(passive)[:400] + ' ## post=' + str(post)[:600] + ' ## alive=' + str((owner.active, owner.reaction_available, owner.current_hp, owner.resources.get('resource:core.stamina'))) + ' ## turnflags=' + str({k:v for k,v in owner.turn_flags.items() if 'pursuit' in k.lower() or 'sky' in k.lower()}))
