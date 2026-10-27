"""Migrated plug-in variant families (combat/ext): one structured family per generator.

Each family is one executable action per legal variant, with ids and effects unchanged; the
family is identified by ActionDefinition.variant, never by parsing display names.
"""
import pytest

from combat.ext import figment
from tests.auto_worker1_support import LEFT as OWNER, fight
from tests.worker2_support import reload

SUBSTANTIAL = "tianxia.talent.illusion.substantial_phantasm"
ILLUSION = "tianxia.sphere.illusion"
SPACE = "tianxia.sphere.space"
WRESTLING = "tianxia.sphere.wrestling"


def _family(engine, axis):
    """A family is found by its structured choice axis (reach, hold, rebuke, slam), never by base key or label:
    Folded Reach and Substantial Phantasm keep their original base keys."""
    return [a for a in engine.action_catalog.values()
            if a.owner_id == OWNER and a.variant is not None and any(p.axis == axis for p in a.variant.choices)]


CHOKE_HOLD = "TAL_WRESTLING_CHOKE_HOLD"
DAO = {"item_id": "tianxia.mortal.weapon.dao", "name": "Dao", "quantity": 1}


def _grant(talent):
    """(talents, spheres, kit) giving a family its base ability: a grapple for the Slam, Create Figment for
    Substantial Phantasm, a melee weapon for Folded Reach. A talent with none of these is granted alone."""
    if talent == "TAL_WRESTLING_GRANDSTANDING_SLAM":
        return [talent, CHOKE_HOLD], [WRESTLING], None
    if talent == SUBSTANTIAL:
        return [figment.SELECTIVE, talent], [figment.SPHERE], None
    if talent == "tianxia.talent.space.folded_reach":
        return [talent], [SPACE], {"items": [DAO]}
    return [talent], [], None


def _axes(actions):
    return {p.axis for a in actions for p in a.variant.choices}


@pytest.mark.parametrize("talent,axis", [
    ("tianxia.talent.space.folded_reach", "reach"),
    (SUBSTANTIAL, "hold"),
    ("foundation.ancient_desolate_sacred_body_v0_2C.saint_body_rebuke", "rebuke"),
    ("TAL_WRESTLING_GRANDSTANDING_SLAM", "slam"),
])
def test_variant_family_is_one_base_with_choice_axes(tmp_path, talent, axis):
    talents, spheres, kit = _grant(talent)
    combat, table, mid = fight(tmp_path, talents, spheres=spheres, left_kit=kit)
    engine = reload(tmp_path, mid)
    family = _family(engine, axis)
    # A talent that stops granting its family must fail here, never skip.
    assert family, f"{talent} must grant a variant family in this fixture"
    assert len({a.variant.base_key for a in family}) == 1, "the family must share one base"
    assert _axes(family) <= {axis, "tempo"}
    for action in family:
        # Choice ids are derived from the executable id, which never changes.
        assert action.source_definition_id
        assert action.variant.base_label
    assert {a.source_definition_id for a in family} <= set(engine.action_catalog)


@pytest.mark.parametrize("talent,axis", [
    ("tianxia.talent.space.folded_reach", "reach"),
    (SUBSTANTIAL, "hold"),
])
def test_structured_choices_name_the_executable_base(tmp_path, talent, axis):
    """Exact choices, and each executable id is its base action plus the choice's own suffix."""
    talents, spheres, kit = _grant(talent)
    combat, table, mid = fight(tmp_path, talents, spheres=spheres, left_kit=kit)
    engine = reload(tmp_path, mid)
    family = _family(engine, axis)
    assert family, f"{talent} must grant a variant family in this fixture"
    expected = {
        "reach": {("reach", "folded", "Folded Reach")},
        "hold": {("hold", "grappled", "Substantial Phantasm: Grappled"), ("hold", "restrained", "Substantial Phantasm: Restrained")},
    }[axis]
    chosen = {(p.axis, p.key, p.label) for a in family for p in a.variant.choices if p.axis == axis}
    assert chosen == expected
    suffix = {"reach": ".folded_reach", "hold": ".substantial."}[axis]
    for action in family:
        base = action.variant.base_key
        assert base in engine.action_catalog, "the base action stays executable in the catalogue"
        assert action.source_definition_id.startswith(base + ".")
        assert suffix in action.source_definition_id[len(base):]


@pytest.mark.parametrize("talent,axis", [
    ("tianxia.talent.space.folded_reach", "reach"),
    (SUBSTANTIAL, "hold"),
])
def test_variant_identity_survives_save_and_cold_reload(tmp_path, talent, axis):
    """ActionDefinition.variant is persisted: the saved catalogue and a cold reload keep every choice."""
    from combat.gate2_runtime_models import ActionDefinition

    talents, spheres, kit = _grant(talent)
    combat, table, mid = fight(tmp_path, talents, spheres=spheres, left_kit=kit)
    engine = reload(tmp_path, mid)
    family = _family(engine, axis)
    assert family, f"{talent} must grant a variant family in this fixture"
    for action in family:
        dumped = action.model_dump(mode="json")
        assert dumped["variant"] == action.variant.model_dump(mode="json")
        again = ActionDefinition.model_validate(dumped)
        assert again.variant == action.variant
        assert again.source_definition_id == action.source_definition_id
    cold = reload(tmp_path, mid)
    reloaded = {a.source_definition_id: a.variant for a in _family(cold, axis)}
    assert reloaded == {a.source_definition_id: a.variant for a in family}


def test_legacy_action_without_variant_serializes_unchanged(tmp_path):
    """Old catalogues carry no variant key: exclude_if=None keeps their serialized shape."""
    from combat.gate2_runtime_models import ActionDefinition

    combat, table, mid = fight(tmp_path, [SUBSTANTIAL], spheres=[ILLUSION])
    engine = reload(tmp_path, mid)
    plain = [a for a in engine.action_catalog.values() if a.owner_id == OWNER and a.variant is None]
    assert plain, "the fixture must carry ordinary actions"
    for action in plain[:20]:
        dumped = action.model_dump(mode="json")
        assert "variant" not in dumped
        assert ActionDefinition.model_validate(dumped).variant is None
