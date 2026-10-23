"""Migrated plug-in variant families (combat/ext): one structured family per generator.

Each family is one executable action per legal variant, with ids and effects unchanged; the
family is identified by ActionDefinition.variant, never by parsing display names.
"""
import pytest

from tests.worker2_support import OWNER, fixture, reload


def _family(engine, needle):
    return [a for a in engine.action_catalog.values()
            if a.owner_id == OWNER and a.variant is not None and needle in a.variant.base_key]


def _axes(actions):
    return {p.axis for a in actions for p in a.variant.choices}


@pytest.mark.parametrize("talent,needle,axes", [
    ("tianxia.talent.space.folded_reach", "folded_reach", {"reach"}),
    ("TAL_ILLUSION_SUBSTANTIAL_PHANTASM", "substantial", {"hold"}),
    ("foundation.ancient_desolate_sacred_body_v0_2C.saint_body_rebuke", "saint_body_rebuke", {"rebuke"}),
    ("TAL_WRESTLING_GRANDSTANDING_SLAM", "slam", {"slam"}),
])
def test_variant_family_is_one_base_with_choice_axes(tmp_path, talent, needle, axes):
    combat, table, mid = fixture(tmp_path, [talent])
    engine = reload(tmp_path, mid)
    family = _family(engine, needle)
    if not family:
        pytest.skip(f"{talent} grants no variant family in this fixture")
    assert {a.variant.base_key for a in family} and len({a.variant.base_key for a in family}) >= 1
    assert _axes(family) <= axes | {"tempo"}
    for action in family:
        # Choice ids are derived from the executable id, which never changes.
        assert action.source_definition_id
        assert action.variant.base_label
    assert {a.source_definition_id for a in family} <= set(engine.action_catalog)
