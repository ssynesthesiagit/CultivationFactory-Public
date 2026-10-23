"""Demon recovery says 'technique', not 'Qi-powered technique'."""
from combat.ext import ancestral_bloodline as bloodline
from combat.factory_compiler import compile_character
from tests.cw2_service_support import add_action, seal
from tests.h1_support import sheet
from tests.test_bloodstrike1 import use, strike_rolls
from tests.worker2_support import OWNER, ALLY, FOE, fixture, reload, turn


def test_stamina_technique_recovers_but_does_not_offer_qi_only_strike(tmp_path):
    doc = sheet([], cl=3, primary="Stamina")
    doc.setdefault("path_and_subpath", {}).update(
        path_feature_record_ids=[bloodline.BLOODLINE],
        bloodline_lineage="demon_ancestry", bloodline_affinity="fire")
    owner = compile_character(doc, actor_id=OWNER)
    def prepare(bundles):
        add_action(bundles[1], "Wound", [{"type": "damage", "applies_to": "target",
                                         "flat": 35, "damage_types": ["force"]}])
        add_action(bundles[0], "Stamina technique", [{"type": "damage", "applies_to": "target",
                                                     "flat": 1, "damage_types": ["force"]}],
                   typed={"source": "tianxia.talent.blood.synthetic"})
        bundles[0]["action_catalog"][-1]["costs"] = [["resource:core.stamina", 1]]
        seal(bundles[0])
    combat, table, mid = fixture(tmp_path, [], primary="Stamina", owner_bundle=owner,
                                 bundle_transform=prepare)
    # Wound from an ally solely prepares low HP. The enemy never damaged the
    # owner, so retaliation cannot make this technique-trigger assertion pass.
    turn(table, mid, ALLY)
    use(combat, table, mid, "Wound", target=OWNER)
    turn(table, mid, OWNER)
    before = reload(tmp_path, mid).state.actors[OWNER].resources["resource:core.stamina"]
    use(combat, table, mid, "Stamina technique", target=FOE)
    engine = reload(tmp_path, mid)
    assert engine.state.actors[OWNER].resources["resource:core.stamina"] == before - 1
    assert engine.state.actors[OWNER].resources[bloodline.RESONANCE] == 1
    assert not strike_rolls(engine)
