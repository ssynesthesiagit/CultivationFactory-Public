"""Shared real-cast fixture for expiry and parser-duplicate tests."""
import copy
from functools import lru_cache
from combat.factory_compiler import compile_character
from combat.gate2_runtime_content import AN
from combat.gate2_runtime_models import ActionIntent
from tests.test_auto_support import ME, _engine
from tests.test_zones import SHEET


FAILS = 30  # the foe's saving throw (a d20 and a small modifier) against this DC never succeeds


@lru_cache(maxsize=None)
def _compiled(sphere: str, talent: str) -> dict:
    stats = {**SHEET["ability_scores_and_statistics"], "technique_save_dc": FAILS}
    return compile_character({**SHEET, "equipment": [], "ability_scores_and_statistics": stats,
                              "spheres_and_talents": {"sphere_record_ids": [sphere], "learned_talent_record_ids": [talent]}}, actor_id=ME)


def _cast(sphere: str, talent: str, name: str, foe_save_bonus: int | None = None):
    engine = _engine(copy.deepcopy(_compiled(sphere, talent)), foe_at=(4, 6))
    if foe_save_bonus is not None:  # a talent whose DC is not technique_save_dc (Wrestling Save DC: 8 + Strength + Proficiency Bonus)
        engine.state.actors[AN].saving_throws.update({ability: foe_save_bonus for ability in ("STR", "DEX", "CON", "INT", "WIS", "CHA")})
    candidate = next(c for c in engine.legal_candidates() if c.display_name == name)
    engine.execute_intent(ActionIntent(intent_id="cast", decision_id=candidate.decision_id, candidate_id=candidate.candidate_id,
                                       state_version=candidate.state_version, actor_id=ME, target_ids=candidate.target_ids,
                                       destination=candidate.destination))
    return engine


