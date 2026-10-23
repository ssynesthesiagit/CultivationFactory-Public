"""The real factory Sword menu honors the disabled Life-Severing control."""
from combat.gate5_service import CombatService, FACTORY_ACTOR_PREFIX
from combat.tabletop_service import TabletopService
from tests.h1_support import ROOT
from tests.test_ocf8_sword_core import (
    _table_sheet, _yard, _press, _auto, BEYOND_HAND, IMMORTAL_BODY, LIFE_SEVERING,
)


def test_disabled_life_severing_has_only_plain_blade_and_keeps_wave_choice(tmp_path):
    project = _table_sheet(tmp_path, hp=400)
    other = _table_sheet(tmp_path, "55555555", hp=400, spheres=(),
                         path_features=(IMMORTAL_BODY,), cl=20)
    fighter, foe = FACTORY_ACTOR_PREFIX + project, FACTORY_ACTOR_PREFIX + other
    combat = CombatService(ROOT, tmp_path)
    mid = combat.create_factory_match(project_ids=[project], opponent_actor_ids=[foe],
        control_modes={fighter: "MANUAL", foe: "LOCAL_AUTO"},
        arena_id=_yard(combat, tmp_path, "disabled-sword"), match_seed="DISABLED-SWORD")["match_id"]
    table = TabletopService(combat, tmp_path)
    for _ in range(20):
        state = table.state(mid)
        menu = state.get("menu") or {}
        if not menu.get("manual"):
            _auto(table, mid, state)
            continue
        groups = [g for g in menu.get("actions", []) if g["label"].startswith(BEYOND_HAND)]
        if not groups:
            setup = next((o["candidate_id"] for g in menu.get("actions", [])
                          if g["label"] == "Finish fight setup" for o in g["options"]), None)
            _press(table, mid, menu, state, candidate=setup)
            continue
        assert [g["label"] for g in groups] == [BEYOND_HAND]
        engine = combat._load_session(mid).engine
        before = dict(engine.state.actors[fighter].resources)
        sequence = engine.state.event_sequence
        candidate = next(o["candidate_id"] for o in groups[0]["options"] if foe in o.get("target_ids", ()))
        asked = []
        _press(table, mid, menu, state, candidate=candidate, asked=asked)
        # Sword Beyond Hand separately prints "Choose the damage type when
        # making the attack." Never silence that decision to hide a paid rider.
        assert [p["reaction"] for p in asked] == ["Sword Qi Wave"]
        engine = CombatService(ROOT, tmp_path)._load_session(mid).engine
        assert engine.state.actors[fighter].resources == before
        assert not [e for e in engine.events if e.sequence > sequence
                    and e.source_definition_id in (LIFE_SEVERING, "passive:" + LIFE_SEVERING)]
        return
    raise AssertionError("Sword Beyond Hand was never offered")
