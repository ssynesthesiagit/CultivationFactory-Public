import json
from pathlib import Path
from types import SimpleNamespace

from combat.ext.mantis_style import eye_first_attack, physical_condition_names


def test_owner_text_edits_source_input_is_retained():
    source = Path(__file__).parents[1] / "authority/typed_mechanics/owner_text_edits.json"

    assert json.loads(source.read_text())


def test_eye_advantage_inspection_does_not_spend_attack_before_roll():
    eye = SimpleNamespace(condition_id="condition:typed.eye_of_the_mantis", source_actor_id="owner",
        data={})
    target = SimpleNamespace(conditions={"eye": eye})
    actor = SimpleNamespace(entity_id="owner", turns_started=1)
    engine = SimpleNamespace(state=SimpleNamespace(
        actors={"owner": actor}, current_actor_id="owner", round_number=1, current_slot_index=0))
    context = SimpleNamespace(actor=actor, engine=engine)

    assert eye_first_attack(engine, actor, target) == "ADVANTAGE"
    assert "attack_turn" not in eye.data


def test_mantis_diagnosis_uses_player_facing_condition_names():
    conditions = [
        SimpleNamespace(condition_id="condition:typed.restrained"),
        SimpleNamespace(condition_id="condition:typed.prone"),
        SimpleNamespace(condition_id="condition:typed.joint_lock"),
        SimpleNamespace(condition_id="condition:typed.restrained"),
    ]

    assert physical_condition_names(conditions) == ["Prone", "Restrained"]
