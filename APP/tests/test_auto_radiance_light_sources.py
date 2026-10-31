"""Radiance forms emit their printed light through the fight-map lighting resolver."""
from tests.test_auto125_radiance import pick
from tests.worker2_flow import settle
from tests.worker2_support import OWNER, fixture

P = "tianxia.talent.radiance."


def test_radiance_forms_emit_printed_bright_and_dim_radii(tmp_path):
    for talent, radii in (
        ("searing_halo", (20, 40)),
        ("solar_radiance_form", (30, 60)),
        ("heavenly_radiance", (120, 240)),
    ):
        combat, table, mid = fixture(tmp_path / talent, [P + talent], seed="RADIANCE-LIGHT-" + talent)
        settle(table, mid, pick(combat, mid, talent.replace("_", " ").title()).candidate_id)
        engine = combat._load_session(mid).engine

        from combat.lighting import sources
        lights = [row for row in sources(engine) if row.following == OWNER and row.entity_id.startswith("radiance:")]
        assert len(lights) == 1
        assert (lights[0].bright_ft, lights[0].dim_ft) == radii
