"""Audited positive-priced custom damage producers use the same strike contract."""
import pytest

from combat.ai_tactics import owned_profile
from combat.ext import ancestral_channeler, dream_eater, echo_step_disciple, grief_eater, parasite_vessel, sand_riders, soul_warden, weather_fields
from tests.h1_support import ME, duel


@pytest.mark.parametrize("talent,suffix,primary", [
    (echo_step_disciple.HUNDRED, ".echo_final_edge", "Resonance"),
    (grief_eater.VESSEL, ".mourners_embrace", "Resonance"),
    (dream_eater.CURSE, ".dream_feed", "Resonance"),
    (parasite_vessel.PREFIX + parasite_vessel.WORM, ".brood_tide", "Stamina"),
    ("TAL_UNMAKING_BLACK_VEIN_STEP", ".black_vein_step.strike", "Qi"),
    (ancestral_channeler.ASCENSION, ".ancestral_authority.warrior", "Resonance"),
    (weather_fields.FINGER, ".TAL_WEATHER_STORMLORD_S_FINGER", "Resonance"),
    (soul_warden.RAISE, ".command.predatory_specter", "Resonance"),
    (sand_riders.MOUTH, ".sand_compress", "Stamina"),
])
def test_custom_damage_is_a_strike_not_utility(talent, suffix, primary):
    engine = duel([talent], primary=primary, cl=18)
    profile = owned_profile(engine, engine.state.actors[ME])["actions"]
    aid = next(key for key in profile if key.endswith(suffix))
    assert profile[aid]["damage"] > 0
    assert profile[aid]["attack"] is True
