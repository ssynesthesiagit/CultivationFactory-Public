"""Public synthetic regression for Split the Chain's printed source exclusion."""
from types import SimpleNamespace

from combat.ext.axes_split_chain import _cultivated


def test_split_the_chain_keeps_secret_cultivation_restraint_on_five_over():
    source_id = "action:typed.air.CYCLONE_PRISON"
    held = SimpleNamespace(
        condition_id="condition:typed.restrained",
        source_actor_id="actor:foe",
        source_definition_id=source_id,
    )
    source = SimpleNamespace(parameters={"typed": {
        "source": "TAL_AIR_CYCLONE_PRISON",
        "source_category": "Secret Inheritance",
        "sphere": "tianxia.sphere.air",
        "weapon": None,
        "numbers": {"save_dc": 15},
    }})
    engine = SimpleNamespace(action_catalog={source_id: source})
    holder = SimpleNamespace(conditions={"restrained-1": held})

    rows = _cultivated(engine, holder)

    assert rows == [("restrained-1", held, 15, False)]
