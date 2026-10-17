from types import SimpleNamespace

from combat.ext.mantis_style import physical_condition_names


def test_mantis_diagnosis_uses_player_facing_condition_names():
    conditions = [
        SimpleNamespace(condition_id="condition:typed.restrained"),
        SimpleNamespace(condition_id="condition:typed.prone"),
        SimpleNamespace(condition_id="condition:typed.joint_lock"),
        SimpleNamespace(condition_id="condition:typed.restrained"),
    ]

    assert physical_condition_names(conditions) == ["Prone", "Restrained"]
