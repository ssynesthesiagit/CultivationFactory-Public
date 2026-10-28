from types import SimpleNamespace

from combat.ext.spatial_absence import ABSENT, recipients


def test_void_interval_allows_only_matching_equal_or_higher_authority():
    target = SimpleNamespace(
        entity_id="absent",
        conditions={"absence": SimpleNamespace(
            condition_id=ABSENT,
            data={"authority_access": ["void", "secret", "conceptual", "samsara", "interstitial"],
                  "authority_cl": 18},
        )},
    )
    ordinary = SimpleNamespace(entity_id="attacker", conditions={})

    def action(category, cl, owner="attacker", interstitial=False):
        return SimpleNamespace(owner_id=owner, parameters={"typed": {
            "sphere": category, "numbers": {"cl": cl},
            "interstitial_authority": interstitial,
        }})

    assert recipients(None, ordinary, target, action("void", 18)) is True
    assert recipients(None, ordinary, target, action("secret", 20)) is True
    assert recipients(None, ordinary, target, action("ordinary", 20, interstitial=True)) is True
    assert recipients(None, ordinary, target, action("void", 17)) is False
    assert recipients(None, ordinary, target, action("ordinary", 20)) is False
    assert recipients(None, ordinary, target, action("void", 20, owner="absent")) is None
