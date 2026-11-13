"""Seeded published arenas exercise menu/preview parity with actual abilities."""
import random

import pytest

from combat.factory_compiler import compile_character
from combat.gate2_runtime_models import ActionIntent, ReactionDecision
from combat.gate4_engine import Gate4ControllerEngine
from combat.gate5_service import CombatService
from tests.h1_support import ROOT, ME, FOE, sheet


@pytest.mark.parametrize('arena', ['ruined-spirit-shrine', 'sect-trial-platform', 'mountain-pass', 'bamboo-forest-ravine'])
@pytest.mark.parametrize('kind', ['walk', 'fly', 'summon'])
def test_seeded_arena_menu_routes(tmp_path, arena, kind):
    combat = CombatService(ROOT, tmp_path)
    battlefield = next(v for k, v in combat.factory_arenas().items() if k.endswith(arena.replace('-', '_')) or k.endswith(arena))
    talents = ['TAL_AIR_WIND_BORNE_BODY'] if kind == 'fly' else ['TAL_BEASTMASTERY_BEAST_TAMER'] if kind == 'summon' else []
    bundle = compile_character(sheet(talents), actor_id=ME,
                               **({'summon_plan': {'beasts': ['wolf']}} if kind == 'summon' else {}))
    engine = Gate4ControllerEngine(ROOT, match_seed='MOVEREJECT-'+arena, typed_bundles=(bundle,), battlefield=battlefield,
        roster_setup={'primary_actor_ids': [ME, FOE], 'team_by_actor': {ME: 'team:a', FOE: 'team:b'},
                      'starting_positions': {ME: {'x': 2, 'y': 7}, FOE: {'x': 12, 'y': 7}}})
    who = ME
    if kind == 'summon':
        who = next(a.entity_id for a in engine.state.actors.values()
                   if a.summon and '.beast0.wolf.' in a.entity_id)
    engine.state.current_slot_index = engine.state.initiative_order.index(who)
    engine.state.current_actor_id = who
    engine._system_start_turn()
    if kind == 'fly':
        actor = engine.state.actors[who]
        engine._apply_condition(actor, 'condition:typed.wind_borne_body', 'TAL_AIR_WIND_BORNE_BODY', who,
            expires_on='END_OF_CURRENT_TURN', data={'fly_speed_ft': 20})
    candidates = [c for c in engine.legal_candidates() if c.kind == 'MOVE']
    assert candidates
    rng = random.Random('MOVEREJECT-'+arena+kind)
    chosen = rng.sample(candidates, min(24, len(candidates)))
    failures = []
    for c in chosen:
        probe = CombatService._clone_engine(ROOT, engine)
        probe.set_reaction_provider(lambda r: (ReactionDecision(checkpoint=r['checkpoint'], reactor_id=r['reactor_id'],
            reaction_source_id=r['reaction_source_id'], selection='DECLINE'), None))
        intent = ActionIntent(intent_id='move-check', decision_id=c.decision_id, candidate_id=c.candidate_id,
            state_version=c.state_version, actor_id=c.actor_id, destination=c.destination)
        try:
            probe.execute_intent(intent)
        except Exception as exc:
            failures.append((c.model_dump(mode='json'), getattr(getattr(exc, 'diagnostic', None), 'code', None), str(exc)))
            if len(failures) == 2:
                break
    assert not failures, failures
