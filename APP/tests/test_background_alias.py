"""Background talents compile under their sphere's own record (owner 2026-09-28: "make sure all the talents ... is applied")."""

from combat.factory_compiler import background_alias


def test_a_background_talent_id_resolves_to_the_same_talent_under_its_sphere():
    mechanics = {"tianxia.talent.music.captivating_melody": {}, "tianxia.talent.harvesting_gathering.camp_gatherer": {}}
    assert background_alias("tianxia.background_talent.music.captivating_melody", mechanics) == "tianxia.talent.music.captivating_melody"
    assert background_alias("tianxia.background_talent.harvesting_and_gathering.camp_gatherer", mechanics) == "tianxia.talent.harvesting_gathering.camp_gatherer"
    assert background_alias("tianxia.background_talent.unknown.thing", mechanics) == "tianxia.background_talent.unknown.thing"
    assert background_alias("TAL_X", mechanics) == "TAL_X"
