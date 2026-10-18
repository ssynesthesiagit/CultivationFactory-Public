"""Physical-suit and rest lifecycle regressions from the second Sol review.

Native service/menu commands and cold journals only; no live server or model.
"""
import pytest

from combat.gate5_service import CombatService
from factory_authoring import owner_items as O
from tests.h1_support import ROOT
from tests.test_mgr_t14_equipment_review import install
from tests.test_mgr_t14_equipment_fix_round import choose
from tests.test_mgr_t14_fitted_armor import ACTOR, PROJECT, LAMELLAR, sheet, fight, support, command, fit
from tests.test_mgr_t14_armor_consumers import finish, heavy_sheet, HEAVY
from tests.test_mgr_t14_armor_defenses import critical_action, strike, HELMET_POOL, damage_action, DAMAGE


def subject(engine):
    return next(b for b in engine.typed_bundle_documents if b["actor_id"] == ACTOR)["armor_subject"]


def test_helmet_only_public_menu_rest_out_of_armor_recovers_use(tmp_path):
    doc = sheet(["helmet_discipline"])
    install(tmp_path, doc)
    choose(CombatService(ROOT, tmp_path), "armor.head_protection", item_key=LAMELLAR, kind="helmet")
    combat, table, mid = fight(tmp_path, doc, prepare=critical_action)
    prompts, used, rolled = strike(combat, table, mid)
    assert prompts and not rolled.payload["critical"]
    assert used.state.actors[ACTOR].resources[HELMET_POOL] == 0
    finish(combat, table, mid)
    combat = CombatService(ROOT, tmp_path)
    menu = combat.character_preparation_options(PROJECT)
    starts = [c for c in menu["commands"] if c["operation"] == "rest.start"]
    assert starts, "Helmet-only characters need a legal public long-rest path"
    assert all(c["parameters"].get("armor_mode") == "removed" for c in starts)
    assert "Lamellar" in starts[0]["label"] and "Helmet Discipline" in starts[0]["label"]
    choose(combat, "rest.start", armor_mode="removed")
    # A fresh service completes the persisted out-of-armor rest.
    state = choose(CombatService(ROOT, tmp_path), "time.advance", observation="sleep")
    assert state["rest_generation"] == 1
    combat, table, mid = fight(tmp_path, doc, prepare=critical_action)
    cold = support._reload(tmp_path, mid)
    assert cold.state.actors[ACTOR].resources[HELMET_POOL] == 1
    assert subject(cold)["head_protection_key"] == LAMELLAR
    prompts, _, rolled = strike(combat, table, mid)
    assert prompts and not rolled.payload["critical"]


def test_heavy_armor_removed_for_sleep_needs_no_sleep_in_armor_or_refit(tmp_path):
    doc = heavy_sheet(["helmet_discipline"])
    install(tmp_path, doc)
    fit(tmp_path, doc, HEAVY)
    choose(CombatService(ROOT, tmp_path), "rest.start", armor_mode="removed")
    state = choose(CombatService(ROOT, tmp_path), "time.advance", observation="sleep")
    assert state["rest_generation"] == 1 and state["armor"]["ready"] == 1
    assert not state["armor"].get("refit_required")
    _, _, mid = fight(tmp_path, doc)
    cold = support._reload(tmp_path, mid)
    from combat.ext.armor_subject import fitted_ready
    assert fitted_ready(cold, cold.state.actors[ACTOR])


def given_setup(root):
    doc = sheet(["helmet_discipline", "hidden_plates"])
    install(root, doc)
    store = O.OwnerItemStore(root / "owner_items")
    chassis = "tianxia.mortal.armor.beast_hide_harness"
    choices = O.armour_choices(chassis, "Spiritual", None, [])
    spec = {"kind": "armour", "chassis_id": chassis, "grade": "Spiritual", "material_id": choices["material_id"]}
    return doc, store, spec


@pytest.mark.parametrize("receipt", ["prepared", "destroyed", "pending"])
def test_removed_given_suit_never_transfers_preparation_to_replacement(tmp_path, receipt):
    doc, store, spec = given_setup(tmp_path)
    first = store.give(PROJECT, spec)
    combat = CombatService(ROOT, tmp_path)
    # The equipped given suit has a worn treasure_armor alias as well as given.0.
    choose(combat, "armor.fit.start", item_key="given.0")
    if receipt != "pending":
        choose(combat, "time.advance", observation="fitting")
        choose(combat, "armor.head_protection", item_key="treasure_armor", kind="helmet")
        choose(combat, "armor.conceal", disguise="travel robes")
    if receipt == "destroyed":
        menu = combat.character_preparation_options(PROJECT)
        combat.character_preparation(PROJECT, "armor.destroy", parameters={"item_key": "given.0"},
                                     expected_revision=menu["state"]["revision"])
    second = store.give(PROJECT, spec)
    assert first["item_uid"] != second["item_uid"]
    store.remove(PROJECT, first["item_uid"])
    cold = CombatService(ROOT, tmp_path)
    if receipt == "destroyed":
        # A different physical suit can be fitted even at the destroyed slot.
        choose(cold, "armor.fit.start", item_key="given.0")
    if receipt == "pending":
        menu = cold.character_preparation_options(PROJECT)
        cold.character_preparation(PROJECT, "time.advance", parameters={"seconds": 600, "observation": "fitting"},
                                   expected_revision=menu["state"]["revision"])
    match = cold.create_factory_match(project_ids=[PROJECT], match_seed="F2-REINDEX-" + receipt, maximum_rounds=1)
    engine = support._reload(tmp_path, match["match_id"])
    facts = subject(engine)
    assert not facts.get("fitted_key"), "The replacement never spent time being fitted"
    assert not facts.get("head_protection_key"), "A recorded helmet belongs to the removed physical suit"
    assert not facts.get("concealed_key"), "The replacement never chose a disguise"
    # The removed suit's destruction receipt must not prohibit fitting this one.
    from combat.ext.armor_subject import fitted_ready
    assert not fitted_ready(engine, engine.state.actors[ACTOR])


@pytest.mark.parametrize("reindex", ["remove", "leave_behind"])
def test_same_given_suit_keeps_preparation_when_earlier_item_is_reindexed(tmp_path, reindex):
    doc, store, spec = given_setup(tmp_path)
    earlier = store.give(PROJECT, spec)
    kept = store.give(PROJECT, spec)
    combat = CombatService(ROOT, tmp_path)
    choose(combat, "armor.fit.start", item_key="given.1")
    choose(combat, "time.advance", observation="fitting")
    choose(combat, "armor.head_protection", item_key="treasure_armor", kind="helmet")
    choose(combat, "armor.conceal", disguise="travel robes")
    if reindex == "remove":
        store.remove(PROJECT, earlier["item_uid"])
    else:
        from combat.tabletop import ButtonStore
        ButtonStore(tmp_path / "tabletop_buttons").save_left_behind(PROJECT, ["given.0"])
    cold = CombatService(ROOT, tmp_path)
    match = cold.create_factory_match(project_ids=[PROJECT], match_seed="F2-KEEP-" + reindex, maximum_rounds=1)
    engine = support._reload(tmp_path, match["match_id"])
    facts = subject(engine)
    from combat.ext.armor_subject import fitted_ready
    assert fitted_ready(engine, engine.state.actors[ACTOR]), "Reindexing cannot revoke this physical suit's fitting"
    assert facts["head_protection_key"] == facts["concealed_key"] == facts["fitted_key"]
    bundle = next(b for b in engine.typed_bundle_documents if b["actor_id"] == ACTOR)
    worn = next(i for i in bundle["carrying"]["items"] if i.get("worn"))
    assert worn["item_uid"] == kept["item_uid"]


@pytest.mark.parametrize("damage", [0, 1000])
def test_combat_interrupts_active_rest_before_cold_continuation(tmp_path, damage):
    doc = sheet(["helmet_discipline", "sleep_in_armor"])
    install(tmp_path, doc)
    choose(CombatService(ROOT, tmp_path), "rest.start", kind="long_rest")
    command(tmp_path, doc, "armor.fit.start", item_key=LAMELLAR)
    def harm(bundle):
        damage_action(bundle)
        if bundle["actor_id"] == support.ATTACKER:
            next(a for a in bundle["action_catalog"] if a["source_definition_id"] == DAMAGE)["parameters"]["typed"]["effects"][0]["flat"] = damage
            support._seal(bundle)
    combat, table, mid = fight(tmp_path, doc, prepare=harm)
    if damage:
        support._commit(combat, table, mid, DAMAGE)
    finish(combat, table, mid)
    hp = support._reload(tmp_path, mid).state.actors[ACTOR].current_hp
    assert (hp == 0) == bool(damage)
    cold = CombatService(ROOT, tmp_path)
    menu = cold.character_preparation_options(PROJECT)
    # Attempt the old sleep/time command, even if its menu button has vanished.
    state = cold.character_preparation(PROJECT, "time.advance", parameters={"seconds": 28800, "observation": "sleep"},
                                       expected_revision=menu["state"]["revision"])
    assert state["rest_generation"] == 0, "An intervening fight must end the old rest"
    assert state["combat_hp"] == hp
    assert state["rest_world"]["actors"][ACTOR]["hp"] == hp
    assert state["rest_world"]["actors"][ACTOR]["activity"]["status"] == "interrupted"
    assert not state["armor"].get("rest_fit_key")
    assert not state["armor"]["ready"]
