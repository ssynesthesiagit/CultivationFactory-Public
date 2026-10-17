"""The real factory Sword menu honors the disabled Life-Severing control."""
from combat.ext.attack_modifiers import chosen, enabled_variant, variant_modifiers
from combat.gate5_service import CombatService, FACTORY_ACTOR_PREFIX
from combat.tabletop_service import TabletopService
from tests.h1_support import ROOT
from tests.test_ocf8_sword_core import (
    _table_sheet, _yard, _press, _auto, BEYOND_HAND, IMMORTAL_BODY, LIFE_SEVERING,
)


def test_disabled_life_severing_has_only_plain_blade(tmp_path):
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
        engine = combat._load_session(mid).engine
        actor = engine.state.actors[fighter]
        details = []
        for group in groups:
            action = engine.action_catalog[group["source_definition_id"]]
            typed = action.parameters.get("typed") or {}
            parent = engine.action_catalog.get(typed.get("attack_modifier_variant") or typed.get("variant_of"))
            pt = (parent.parameters.get("typed") or {}) if parent else {}
            details.append({
                "name": action.display_name, "source": action.source_definition_id,
                "owner": actor.owner_id, "modes": engine.typed_control_modes,
                "marker": typed.get("attack_modifier_variant"), "variant_of": typed.get("variant_of"),
                "modifier": typed.get("modifier"), "selected": typed.get("selected_modifiers"),
                "controls": variant_modifiers(action, engine.action_catalog.values()),
                "groups": pt.get("attack_modifier_loadout"),
                "saved": chosen(actor, parent.source_definition_id, LIFE_SEVERING) if parent else {},
                "admitted": enabled_variant(engine, actor, None, action),
            })
        assert not [g for g in groups if "Life-Severing Sword" in g["label"]], details
        return
    raise AssertionError("Sword Beyond Hand was never offered")
