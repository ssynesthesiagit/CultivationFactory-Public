"""Halo of the Merciful Sovereign lights its ally through the real table lighting resolver."""
from tests.test_auto125_radiance import pick
from tests.worker2_flow import settle
from tests.worker2_support import ALLY, OWNER, fixture

P = "tianxia.talent.radiance."


def test_merciful_halo_emits_bright_light_from_its_willing_target(tmp_path):
    combat, table, mid = fixture(tmp_path, [P + "halo_of_the_merciful_sovereign"],
                                 extra_allies=1, seed="RADIANCE-MERCIFUL-HALO-LIGHT")
    settle(table, mid, pick(combat, mid, "Halo of the Merciful Sovereign", target=ALLY).candidate_id)
    engine = combat._load_session(mid).engine

    from combat.lighting import sources
    lights = [row for row in sources(engine) if row.following == ALLY and row.entity_id.startswith("radiance:")]
    assert len(lights) == 1
    assert (lights[0].bright_ft, lights[0].dim_ft) == (10, 10)
