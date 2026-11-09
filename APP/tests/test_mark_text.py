"""A mark's hover says whose it is, what placed it, when it ends and which abilities read it (owner 2026-09-29)."""

from types import SimpleNamespace

from combat.tabletop_service import TabletopService

OWNER = "actor:factory.c328"
MIND_SPIKE = "action:typed.6fc7abb5f6.tianxia.path.spirit_awakening.feature.mind_spike"
SOUL_GAZE = "action:typed.6fc7abb5f6.tianxia.path.spirit_awakening.feature.soul_gaze"


def test_a_resonance_mark_explains_itself():
    engine = SimpleNamespace(action_catalog={MIND_SPIKE: SimpleNamespace(owner_id=OWNER), SOUL_GAZE: SimpleNamespace(owner_id=OWNER)})
    row = {"condition_id": f"condition:typed.mark.resonance.{OWNER}", "source_definition_id": MIND_SPIKE, "expires_on": "END_OF_MARKER_NEXT_TURN", "detail": None}
    presentation = {"actors": [{"conditions": [row]}]}
    TabletopService._explain_marks(TabletopService, presentation, engine, {OWNER: "Mei Jiang"}, {MIND_SPIKE: "Mind Spike", SOUL_GAZE: "Soul Gaze"})
    detail = row["detail"]
    assert detail.startswith("Resonance mark from Mei Jiang (Mind Spike), until the end of its placer's next turn.")
    assert "Spirit Awakening" in detail and "Soul Gaze" in detail
