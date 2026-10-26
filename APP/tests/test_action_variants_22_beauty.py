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


def test_shared_spotlight_aura_has_distinct_structured_family():
    from combat.ext.beauty_adorn import spotlight, SHARED
    info = {**INFO, "owned_ids": [adorn.ADORN, SHARED], "actions": []}
    ordinary = adorn.aura_choices(info)[0]
    shared = spotlight(info)[0]
    assert ordinary.variant.base_key != shared.variant.base_key
    assert ordinary.variant.base_label == "Adorn the Moment"
    assert shared.variant.base_label == "Adorn the Moment + Shared Spotlight"
    assert [(part.axis, part.key) for part in ordinary.variant.choices] == [("aura", "soft")]
    assert [(part.axis, part.key) for part in shared.variant.choices] == [
        ("aura", "soft"), ("recipients", "self_and_ally")]
    assert shared.source_definition_id.endswith(".shared_spotlight")


def test_shared_spotlight_compiled_check_and_memory_options_keep_distinct_labels():
    from combat.ext.beauty_adorn import spotlight, SHARED

    compiled = []
    for ix, label in enumerate(("Advantage on Check", "Visually Memorable")):
        action = adorn.aura_choices(INFO)[0].model_copy(update={
            "source_definition_id": f"action:typed.{adorn.ADORN}#opt{ix}",
            "display_name": f"Adorn the Moment: {label}",
            "variant": None,
            "parameters": {**adorn.aura_choices(INFO)[0].parameters, "typed": {
                **adorn.aura_choices(INFO)[0].parameters["typed"],
                "option_label": label, "effects": [{"type": "adorn_check" if ix == 0 else "adorn_memory"}],
            }},
        })
        compiled.append(action)
    info = {**INFO, "owned_ids": [adorn.ADORN, SHARED], "actions": compiled}

    shared = spotlight(info)
    assert [a.variant.base_label for a in shared] == ["Adorn the Moment + Shared Spotlight"] * 2
    assert [variant_name(a.variant) for a in shared] == [
        "Adorn the Moment + Shared Spotlight + Advantage on Check + Shared Spotlight",
        "Adorn the Moment + Shared Spotlight + Visually Memorable + Shared Spotlight",
    ]
    assert [a.variant.choices[0].key for a in shared] == ["advantage_check", "visually_memorable"]
    assert [a.parameters["typed"]["effects"][1]["effects"] for a in shared] == [
        [{"type": "adorn_check"}], [{"type": "adorn_memory"}],
    ]


def test_no_adorn_auras_without_the_talent():
    assert adorn.aura_choices({**INFO, "owned_ids": []}) is None
