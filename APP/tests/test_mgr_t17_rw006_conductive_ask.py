"""MGR-T17 RW006 review fix (Sol, blocking): Conductive Strike's CL 5 Charge spend is the player's choice, asked on the hit.

The printed rule reads "At CL 5, if the target is already Charged, you may consume the Charge to increase the additional
lightning damage to 1d8 + your Proficiency Bonus". The after-hit hook used to spend the Charge with no ask, so the target was
drained for the player. Fixed in combat/ext/charge_marks.py (needle.ask, default decline). These table-level tests drive a real
engine attack and fail on the old automatic spend.
"""

from combat.gate2_runtime_models import ReactionDecision
from tests.test_riders_lane1 import AN, ME, _bears, _bundle, _engine, _mark, _rider_strike

CS = "TAL_LIGHTNING_CONDUCTIVE_STRIKE"


def _answer(engine, pick):
    """Answer only the Conductive Strike ask; ``pick`` True consumes the Charge, False declines. Other asks decline."""
    seen = []

    def provider(request):
        base = dict(checkpoint=request["checkpoint"], reactor_id=request["reactor_id"], reaction_source_id=request["reaction_source_id"])
        if "extension_choice" not in request:
            return ReactionDecision(**base, selection="DECLINE", option_ids=()), None
        seen.append(request)
        if pick and request["reaction_source_id"].endswith("conductive_strike"):
            return ReactionDecision(**base, selection="USE", option_ids=("CONSUME",)), None
        return ReactionDecision(**base, selection="DECLINE", option_ids=()), None

    engine.set_reaction_provider(provider)
    return seen


def _drop_on_weapon_hit(pick=None, *, charged=True):
    engine = _engine(_bundle(CS, cl=17), {})
    if charged:
        _mark(engine, AN, "Charged")
    seen = _answer(engine, pick) if pick is not None else []
    foe = engine.state.actors[AN]
    before = foe.current_hp
    _rider_strike(engine, ME, AN, kind="weapon")
    return engine, foe, before - foe.current_hp, seen


def test_declining_the_cl5_spend_keeps_the_charge_and_does_not_drain_the_target():
    engine, foe, declined_drop, seen = _drop_on_weapon_hit(pick=False)
    assert any(r["reaction_source_id"].endswith("conductive_strike") for r in seen)  # asked on the hit
    assert _bears(engine, AN, "Charged")  # not spent for the player
    assert _bears(engine, AN, "Conductive")  # the mark itself is automatic
    _, _, control_drop, _ = _drop_on_weapon_hit(charged=False)  # same hit, no Charge: no CL 5 choice at all
    assert declined_drop == control_drop  # no extra 1d8 was taken


def test_consuming_the_charge_on_the_cl5_ask_spends_it_and_adds_the_extra_damage():
    engine, foe, accepted_drop, seen = _drop_on_weapon_hit(pick=True)
    assert any(r["reaction_source_id"].endswith("conductive_strike") for r in seen)
    assert not _bears(engine, AN, "Charged")
    assert _bears(engine, AN, "Conductive")
    _, _, declined_drop, _ = _drop_on_weapon_hit(pick=False)
    assert accepted_drop > declined_drop  # the extra 1d8 lightning damage


def test_an_unanswered_cl5_ask_declines_so_nothing_is_spent_for_the_player():
    engine, foe, drop, _ = _drop_on_weapon_hit()  # no reaction provider: nobody answers
    assert _bears(engine, AN, "Charged") and _bears(engine, AN, "Conductive")
