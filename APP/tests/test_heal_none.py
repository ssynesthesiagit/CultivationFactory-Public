""""cannot regain HP" is a no-healing effect, like "cannot regain hit points" (Black Trace's Fray was left a GM line)."""

from factory_authoring.typed_structure import healing_reduction_amount


def test_cannot_regain_hp_blocks_healing():
    assert healing_reduction_amount("The target cannot regain HP until the start of your next turn.") == "none"
    assert healing_reduction_amount("it can’t regain hit points until the start of its next turn") == "none"
    assert healing_reduction_amount("when it is reduced to 0 HP") is None
