"""Migrated plug-in variant families (combat/ext): one structured family per generator.

Each family is one executable action per legal variant, with ids and effects unchanged; the
family is identified by ActionDefinition.variant, never by parsing display names.
"""
import pytest

from tests.auto_worker1_support import LEFT as OWNER, fight
from tests.worker2_support import reload

SUBSTANTIAL = "tianxia.talent.illusion.substantial_phantasm"
ILLUSION = "tianxia.sphere.illusion"
SPACE = "tianxia.sphere.space"
WRESTLING = "tianxia.sphere.wrestling"


def _family(engine, needle):
    return [a for a in engine.action_catalog.values()
            if a.owner_id == OWNER and a.variant is not None and needle in a.variant.base_key]


def _sphere(talent):
    """The sphere each talent is learned from; a talent with none is granted without one."""
    return {"tianxia.talent.space.folded_reach": SPACE, SUBSTANTIAL: ILLUSION, "TAL_WRESTLING_GRANDSTANDING_SLAM": WRESTLING}.get(talent, "")


def _axes(actions):
    return {p.axis for a in actions for p in a.variant.choices}


@pytest.mark.parametrize("talent,needle,axes", [
    ("tianxia.talent.space.folded_reach", "folded_reach", {"reach"}),
    (SUBSTANTIAL, "substantial", {"hold"}),
    ("foundation.ancient_desolate_sacred_body_v0_2C.saint_body_rebuke", "saint_body_rebuke", {"rebuke"}),
    ("TAL_WRESTLING_GRANDSTANDING_SLAM", "slam", {"slam"}),
])
def test_variant_family_is_one_base_with_choice_axes(tmp_path, talent, needle, axes):
    combat, table, mid = fight(tmp_path, [talent], spheres=[s for s in [_sphere(talent)] if s])
    engine = reload(tmp_path, mid)
    family = _family(engine, needle)
    # A talent that stops granting its family must fail here, never skip.
    assert family, f"{talent} must grant a variant family in this fixture"
    assert len({a.variant.base_key for a in family}) == 1, "the family must share one base"
    assert _axes(family) <= axes | {"tempo"}
    for action in family:
        # Choice ids are derived from the executable id, which never changes.
        assert action.source_definition_id
        assert action.variant.base_label
    assert {a.source_definition_id for a in family} <= set(engine.action_catalog)


@pytest.mark.parametrize("talent,needle", [
    ("tianxia.talent.space.folded_reach", "folded_reach"),
    (SUBSTANTIAL, "substantial"),
])
def test_variant_identity_survives_save_and_cold_reload(tmp_path, talent, needle):
    """ActionDefinition.variant is persisted: the saved catalogue and a cold reload keep every choice."""
    from combat.gate2_runtime_models import ActionDefinition

    combat, table, mid = fight(tmp_path, [talent], spheres=[s for s in [_sphere(talent)] if s])
    engine = reload(tmp_path, mid)
    family = _family(engine, needle)
    assert family, f"{talent} must grant a variant family in this fixture"
    for action in family:
        dumped = action.model_dump(mode="json")
        assert dumped["variant"] == action.variant.model_dump(mode="json")
        again = ActionDefinition.model_validate(dumped)
        assert again.variant == action.variant
        assert again.source_definition_id == action.source_definition_id
    cold = reload(tmp_path, mid)
    reloaded = {a.source_definition_id: a.variant for a in _family(cold, needle)}
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
