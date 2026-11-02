"""F17 review: unrelated authority survives; Burning Weapon's Fire profile is intentional."""
import json

from combat.gate5_service import CombatService
from combat.observer_information import source_profile
from combat.tabletop_service import TabletopService
from tests.h1_support import ROOT
from tests.r1i_service_support import FOE, OWNER, fixture
from tests.test_auto77f1_fire_service import (
    AXE, BURN, KIT, _candidate, _condition, _run,
)

SACRAL = "tianxia.tradition.spirit.inner_soul_gate_ascetic.feature.sacral_soul_gate"
HISTORICAL_SACRAL = {
    "text_sha256": "7a47a0f43ccba1b2ab011210205c31b49f2dd7dbaad41b66bfcf4696c5b490cf",
    "reviewed_by": "paths 2026-09-28",
    "modifier": None,
    "riders": [
        "Sacral Reorientation (Reaction, once per round, spend 2 Resonance: add your Wisdom modifier to a failed Dexterity, Wisdom or Charisma saving throw, which can turn a failure into a success) is applied by hand -- the game never offers it to you, so the GM grants it."
    ],
}


def test_sacral_historical_entry_is_restored_without_replacing_newer_automation():
    """Keep the requested historical entry exactly, but do not revive its obsolete manual behavior."""
    shards = ROOT / "authority/typed_mechanics/reviewed_final.d"
    paths = json.loads((shards / "paths.json").read_text())["mechanics"]
    assert paths[SACRAL] == HISTORICAL_SACRAL
    newer = json.loads((shards / "subpaths.json").read_text())["mechanics"][SACRAL]
    built = json.loads((ROOT / "authority/Tianxia_Typed_Mechanics_Authority_R1.json").read_text())["mechanics"][SACRAL]
    assert built["typing_status"] == "reviewed_final"
    assert built["effects"] == newer["effects"]
    assert any(row.get("runs") == "combat/ext/inner_soul_gate.py" for row in built["effects"])
    assert built["riders"] == newer["riders"]
    assert HISTORICAL_SACRAL["riders"][0] not in built["riders"]
    assert built["activation"] == newer["activation"]


def test_printed_burning_weapon_fire_profile_survives_commit_reload_and_hit(tmp_path):
    """No Cremation owner is present: 'add Fire damage' and 'The hit applies Burn' still govern."""
    texts = json.loads((ROOT / "authority/typed_mechanics/rules_text.json").read_text())
    assert "add Fire damage" in texts[BURN] and "The hit applies Burn." in texts[BURN]
    combat, table, mid, _send, _commit = fixture(
        tmp_path, [BURN], owner_kit=KIT, owner_cl=17, foe_ac=0,
    )
    _run(table, mid, _candidate(combat, table, mid, "Burning Weapon", OWNER),
         lambda prompt, choice, ids: ["tianxia.mortal.weapon.fu"])

    # A fresh service, not the in-memory engine that created the imbuement.
    combat = CombatService(ROOT, tmp_path)
    table = TabletopService(combat, tmp_path)
    engine = combat._load_session(mid).engine
    (imbuement,) = _condition(engine.state.actors[OWNER], "state.burning_weapon")
    assert imbuement.data["damage_types"] == ["fire"]
    assert imbuement.expires_on == "CONCENTRATION_END"
    assert source_profile(engine, imbuement.source_definition_id, imbuement.data)["damage_types"] == ["FIRE"]
    assert not _condition(engine.state.actors[FOE], "state.burning_weapon")
    # A real attack can roll a natural 1 even against AC 0. Retry only an
    # actual miss on a later native turn; never substitute fabricated damage.
    for attempt in range(4):
        first_sequence = combat._load_session(mid).engine.state.event_sequence
        _run(table, mid, _candidate(combat, table, mid, AXE, FOE),
             lambda prompt, choice, ids: None)
        session = CombatService(ROOT, tmp_path)._load_session(mid)
        after = session.engine
        events = [e for e in after.events if e.sequence > first_sequence]
        attacks = [e for e in events if e.event_type == "ATTACK_ROLLED"]
        assert attacks, [(e.event_type, dict(e.payload)) for e in events]
        if any(e.payload.get("provisional_hit") for e in attacks):
            break
        assert attempt < 3, [dict(e.payload) for e in attacks]
        # All seats are manual; pass their turns without attacking the caster.
        for _ in range(4):
            _run(table, mid, table.state(mid)["menu"]["end_turn"],
                 lambda prompt, choice, ids: None)
            if table.state(mid)["menu"]["actor_id"] == OWNER:
                break
        else:
            raise AssertionError("the bearer did not receive its next turn")

    packets = [e for e in events
               if e.event_type == "DAMAGE_COMMITTED" and FOE in e.target_ids
               and e.payload.get("damage_type") == "FIRE"]
    assert packets, [(e.event_type, dict(e.payload)) for e in events]
    assert any(e.event_type == "DAMAGE_ROLLED" and
               str(e.payload.get("expression", "")).removesuffix("+0") == "3d6"
               for e in events)
    assert _condition(after.state.actors[FOE], "burning")
    (remaining,) = _condition(after.state.actors[OWNER], "state.burning_weapon")
    assert remaining.data["damage_types"] == ["fire"]
    assert source_profile(after, remaining.source_definition_id, remaining.data)["damage_types"] == ["FIRE"]
    assert session.mechanical.replay()["status"] == "PASS"
