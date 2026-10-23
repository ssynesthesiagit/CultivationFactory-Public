"""Public synthetic table regressions for lineage recovery and affinity permissions."""
import pytest

from combat.ext import ancestral_bloodline as bloodline
from combat.factory_compiler import compile_character
from tests.cw2_service_support import add_action
from tests.h1_support import sheet
from tests.test_bloodstrike1 import use, strike_rolls
from tests.worker2_support import OWNER, ALLY, FOE, fixture, reload, settle, turn

POOL = bloodline.RESONANCE


def document(lineage, affinity):
    doc = sheet([], cl=3)
    doc.setdefault("path_and_subpath", {}).update(
        path_feature_record_ids=[bloodline.BLOODLINE],
        bloodline_lineage=lineage, bloodline_affinity=affinity)
    return doc


def make(tmp_path, lineage, affinity):
    bundle = compile_character(document(lineage, affinity), actor_id=OWNER)
    def prepare(bundles):
        for b in bundles:
            for name, effects, typed in [
                ("Wound", [{"type": "damage", "applies_to": "target", "flat": 35,
                            "damage_types": ["force"]}], {}),
                ("Brace", [{"type": "resistance", "applies_to": "target", "damage_types": ["force"],
                            "duration": {"kind": "until_removed"}}], {}),
                ("Push", [{"type": "forced_movement", "applies_to": "target",
                           "distance_ft": 10, "direction": "away"}], {}),
                ("Poke", [{"type": "damage", "applies_to": "target", "flat": 1,
                           "damage_types": ["force"]}], {}),
                ("Heal", [{"type": "healing", "applies_to": "target", "flat": 2}], {}),
                ("Poison", [{"type": "condition", "condition": "poisoned", "applies_to": "target",
                             "duration": {"kind": "until_removed"}}], {}),
                ("Cure", [{"type": "remove_condition", "condition": "poisoned", "applies_to": "target"}], {}),
                ("Qi blow", [{"type": "damage", "applies_to": "target", "flat": 1,
                             "damage_types": ["force"]}], {"qi_powered": True}),
                ("Resist fire", [{"type": "save", "ability": "dex", "dc": 1,
                                  "save_categories": ["fire"], "on_fail": [
                                      {"type": "damage", "flat": 1, "damage_types": ["fire"]}]}], {}),
                ("Resist earth", [{"type": "save", "ability": "dex", "dc": 1,
                                   "save_categories": ["earth"], "on_fail": [
                                       {"type": "damage", "flat": 1, "damage_types": ["bludgeoning"]}]}], {}),
                ("Resist fear", [{"type": "save", "ability": "wis", "dc": 1,
                                  "on_fail": [{"type": "condition", "condition": "frightened"}]}], {}),
                ("Remain standing", [{"type": "save", "ability": "str", "dc": 1,
                                      "on_fail": [{"type": "condition", "condition": "prone"}]}], {}),
                ("Misdirect", [{"type": "save", "ability": "wis", "dc": 100,
                               "save_categories": ["misdirection"], "on_fail": [
                                   {"type": "condition", "condition": "reaction_denied"}]}], {}),
            ]:
                if effects[0]["type"] == "save":
                    typed = {**typed, "numbers": {"pb": 2, "key_mod": 2, "cl": 3,
                                                  "save_dc": effects[0].pop("dc")}}
                add_action(b, name, effects, typed=typed)
    return fixture(tmp_path, [], owner_bundle=bundle, bundle_transform=prepare, named=True)


def balance(tmp_path, mid):
    return reload(tmp_path, mid).state.actors[OWNER].resources[POOL]


@pytest.mark.parametrize("lineage,affinity,title,acting,target", [
    ("azure_dragon", "fire", "Resist fire", FOE, OWNER),
    ("azure_dragon", "fire", "Resist earth", FOE, OWNER),
    ("jade_tortoise", "force", "Remain standing", FOE, OWNER),
    ("nine_tailed_fox", "psychic", "Misdirect", OWNER, FOE),
    ("heavenly_serpent", "poison", "Poison", OWNER, FOE),
    ("demon_ancestry", "fire", "Resist fear", FOE, OWNER),
])
def test_save_and_condition_trigger_families_commit_reload(tmp_path, lineage, affinity, title, acting, target):
    combat, table, mid = make(tmp_path, lineage, affinity)
    assert balance(tmp_path, mid) == 0
    turn(table, mid, acting)
    use(combat, table, mid, title, target=target)
    assert balance(tmp_path, mid) == 1
    use(combat, table, mid, title, target=target)
    assert balance(tmp_path, mid) == 1


@pytest.mark.parametrize("trigger", ["healing", "survival"])
def test_phoenix_below_half_recovery(tmp_path, trigger):
    combat, table, mid = make(tmp_path, "vermilion_phoenix", "fire")
    turn(table, mid, FOE)
    use(combat, table, mid, "Wound", target=ALLY if trigger == "healing" else OWNER)
    assert balance(tmp_path, mid) == 0
    if trigger == "healing":
        turn(table, mid, OWNER)
        use(combat, table, mid, "Heal", target=ALLY)
    else:
        use(combat, table, mid, "Poke", target=OWNER)
    assert balance(tmp_path, mid) == 1


def test_qilin_cures_harmful_condition(tmp_path):
    combat, table, mid = make(tmp_path, "qilin", "radiant")
    turn(table, mid, FOE)
    use(combat, table, mid, "Poison", target=ALLY)
    assert balance(tmp_path, mid) == 0
    turn(table, mid, OWNER)
    use(combat, table, mid, "Cure", target=ALLY)
    assert balance(tmp_path, mid) == 1
    use(combat, table, mid, "Cure", target=ALLY)
    assert balance(tmp_path, mid) == 1


@pytest.mark.parametrize("lineage,affinity,target", [
    ("jade_tortoise", "force", OWNER),
    ("qilin", "radiant", ALLY),
])
def test_preventing_damage_recovers_for_its_provider(tmp_path, lineage, affinity, target):
    combat, table, mid = make(tmp_path, lineage, affinity)
    use(combat, table, mid, "Brace", target=target)
    assert balance(tmp_path, mid) == 0
    turn(table, mid, FOE)
    use(combat, table, mid, "Wound", target=target)
    assert balance(tmp_path, mid) == 1


def test_kunpeng_forced_movement(tmp_path):
    combat, table, mid = make(tmp_path, "kunpeng", "cold")
    use(combat, table, mid, "Push", target=FOE)
    assert balance(tmp_path, mid) == 1


def test_kunpeng_twenty_feet_earns_and_pays_strike(tmp_path):
    combat, table, mid = make(tmp_path, "kunpeng", "cold")
    for _ in range(4):
        engine = reload(tmp_path, mid)
        # A one-square route permits four separately committed moves.
        moves = [c for c in engine.legal_candidates() if c.kind == "MOVE"
                 and c.destination and c.destination.y == 6
                 and c.destination.x == (2 if engine.state.actors[OWNER].position.x == 3 else 3)]
        assert moves
        settle(table, mid, moves[0].candidate_id)
    assert balance(tmp_path, mid) == 1
    use(combat, table, mid, "Qi blow", target=FOE)
    assert len(strike_rolls(reload(tmp_path, mid))) == 1
    assert balance(tmp_path, mid) == 0


def test_demon_low_hp_technique_and_retaliation(tmp_path):
    combat, table, mid = make(tmp_path, "demon_ancestry", "fire")
    turn(table, mid, FOE)
    use(combat, table, mid, "Wound", target=OWNER)
    assert balance(tmp_path, mid) == 0
    turn(table, mid, OWNER)
    use(combat, table, mid, "Poke", target=FOE)
    assert balance(tmp_path, mid) == 1
    use(combat, table, mid, "Qi blow", target=FOE)
    assert balance(tmp_path, mid) == 0
    turn(table, mid, ALLY)
    turn(table, mid, OWNER)
    use(combat, table, mid, "Qi blow", target=FOE)
    assert len(strike_rolls(reload(tmp_path, mid))) == 2


def test_illegal_phoenix_preset_rejected():
    with pytest.raises(ValueError, match="not permitted"):
        compile_character(document("vermilion_phoenix", "cold"), actor_id=OWNER)


@pytest.mark.parametrize("affinity", ["earth", "water"])
def test_tortoise_principles_are_legal_and_deal_canonical_damage(tmp_path, affinity):
    combat, table, mid = make(tmp_path, "jade_tortoise", affinity)
    turn(table, mid, FOE)
    use(combat, table, mid, "Remain standing", target=OWNER)
    turn(table, mid, OWNER)
    use(combat, table, mid, "Qi blow", target=FOE)
    engine = reload(tmp_path, mid)
    assert len(strike_rolls(engine)) == 1
    packet, = [e for e in engine.events if e.event_type == "DAMAGE_COMMITTED"
               and e.payload.get("display_source_id") == bloodline.BLOODLINE]
    assert packet.payload["damage_type"] == "BLUDGEONING"


def test_interactive_phoenix_does_not_offer_cold(tmp_path):
    # The ordinary construction list must preserve every legal option, not
    # offer an invalid combination and reject it after the player chooses.
    bundle = compile_character(document("vermilion_phoenix", ""), actor_id=OWNER)
    actions = [row["display_name"] for row in bundle["action_catalog"]
               if ".bloodline_affinity." in row["source_definition_id"]]
    assert set(actions) == {"Bloodline affinity: Fire", "Bloodline affinity: Radiant"}


@pytest.mark.parametrize("discarded,earned", [(15, True), (3, False)])
def test_fox_disadvantage_must_cause_the_miss(monkeypatch, discarded, earned):
    from types import SimpleNamespace as NS
    target = NS(entity_id=OWNER, team_id="allies", conditions={"setting": NS(
        condition_id=bloodline.AFFINITY, data={"lineage": "nine_tailed_fox"})})
    attacker = NS(entity_id=FOE, team_id="enemies", conditions={})
    roll = NS(event_type="ATTACK_ROLLED", actor_id=FOE, target_ids=(OWNER,), payload={
        "mode": "DISADVANTAGE", "discarded": [discarded], "natural_result": 2,
        "total": 7, "target_ac": 14})
    engine = NS(state=NS(actors={OWNER: target, FOE: attacker}), events=[roll])
    gains = []
    monkeypatch.setattr(bloodline, "gain_resonance", lambda engine, actor: gains.append(actor.entity_id))
    bloodline.resonance_missed(engine, NS(target_id=OWNER, attacker_id=FOE, hit=False), None)
    assert gains == ([OWNER] if earned else [])


def test_demon_construction_setting_is_not_a_technique(tmp_path):
    bundle = compile_character(document("demon_ancestry", ""), actor_id=OWNER)
    def prepare(bundles):
        add_action(bundles[2], "Wound", [{"type": "damage", "applies_to": "target",
                                         "flat": 35, "damage_types": ["force"]}])
    combat, table, mid = fixture(tmp_path, [], owner_bundle=bundle, bundle_transform=prepare)
    turn(table, mid, FOE)
    use(combat, table, mid, "Wound", target=OWNER)
    turn(table, mid, OWNER)
    use(combat, table, mid, "Bloodline affinity: Fire", target=OWNER)
    assert balance(tmp_path, mid) == 0
