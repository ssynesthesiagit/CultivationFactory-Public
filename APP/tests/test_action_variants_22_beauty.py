"""Adorn the Moment's printed aura choice is one family with one variant per tone (VARIANTS22)."""
from combat.action_variants import variant_name
from combat.ext import beauty_adorn_base as adorn

INFO = {"short": "beauty", "actor_id": "actor:test", "owned_ids": [adorn.ADORN], "numbers": {}}


def test_adorn_auras_are_one_family_with_one_tone_axis_each():
    actions = adorn.aura_choices(INFO)
    assert [a.source_definition_id for a in actions] == [
        f"action:typed.beauty.{adorn.ADORN}#aura_{tone}" for tone in adorn.TONES]
    bases = {a.variant.base_key for a in actions}
    assert bases == {f"action:typed.beauty.{adorn.ADORN}"}
    assert all(a.variant.base_label == "Adorn the Moment" for a in actions)
    for tone, action in zip(adorn.TONES, actions):
        assert [(c.axis, c.key) for c in action.variant.choices] == [("aura", tone)]
        assert all(c.costs == () for c in action.variant.choices)
        assert variant_name(action.variant) == f"Adorn the Moment + {tone.title()} aura"


def test_adorn_auras_keep_their_ids_names_and_effects():
    actions = adorn.aura_choices(INFO)
    for tone, action in zip(adorn.TONES, actions):
        assert action.display_name == f"Adorn the Moment: {tone.title()} aura"
        assert action.parameters["typed"]["effects"] == [{"type": "adorn_aura", "tone": tone}]
        assert action.costs == ()
        assert action.economy == "BONUS_ACTION"


def test_no_adorn_auras_without_the_talent():
    assert adorn.aura_choices({**INFO, "owned_ids": []}) is None
