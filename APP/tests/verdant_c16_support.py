"""Shared Verdant Growth identifiers and mark lookup for C16 table tests."""

VG = "TAL_VERDANT_GROWTH_"
SOWN = VG + "SOW_LIVING_CLAIM"
SEED = VG + "SEED_THORN_STRIKE"


def growth(engine, who, owner="actor:factory.c16_me"):
    from combat.ext import verdant_chassis

    return verdant_chassis.marks(engine.state.actors[who], engine.state.actors[owner])
