"""Immediate Bloom's real persisted-table menu explains the talent paid for."""

from combat.ext import blossom
from combat.factory_compiler import compile_character
from tests.h1_support import sheet
from tests.h48_table_support import OWNER, fixture


LABEL = "Cultivate Blossom (bloom at once)"


def _description(table, match_id):
    return next(group["description"] for group in table.state(match_id)["menu"]["actions"]
                if group["label"] == LABEL)


def test_sphere_only_immediate_bloom_menu_explains_default_heal_recipient_and_cost(tmp_path):
    def sphere_only(bundles):
        document = sheet("TAL_FLOWERS_CULTIVATE_BLOSSOM", cl=17)
        document["spheres_and_talents"]["learned_talent_record_ids"] = []
        bundles[0] = compile_character(document, actor_id=OWNER)

    _, table, match_id, _, _ = fixture(tmp_path, [], seed="solfmmx109r2-default", bundle_transform=sphere_only)
    groups = table.state(match_id)["menu"]["actions"]
    assert not any(group["label"].startswith("Blossom: ") for group in groups)
    text = _description(table, match_id)
    for required in ("Costs an Action", "within 60 feet", "Medicinal Blossom is the default",
                     "Medicinal Blossom — 1 Cultivation Point", "heals 3d8 + your Path key ability modifier HP immediately",
                     "wounded ally (including you) within 5 feet", "lowest fraction of HP remaining",
                     "only once per short rest", "still pay the point cost"):
        assert required in text
    assert "Thorned Bloom" not in text


def test_selected_thorned_bloom_menu_explains_changed_effect_cost_and_duration(tmp_path):
    _, table, match_id, _, commit = fixture(tmp_path, [blossom.THORN], seed="solfmmx109r2-thorns")
    group = next(group for group in table.state(match_id)["menu"]["actions"]
                 if group["label"] == "Blossom: Thorned Bloom (2 CP)")
    commit(group["options"][0]["candidate_id"])
    text = _description(table, match_id)
    for required in ("resolving your selected Blossom talent", "Use the Blossom: talent buttons",
                     "selection stays until changed", "Thorned Bloom — 2 Cultivation Points",
                     "10-foot-radius field centered on the Blossom", "Concentration, up to 1 minute",
                     "difficult terrain (movement costs twice as much)", "enemy entering it",
                     "starting its turn there", "Dexterity save", "6d6 Piercing damage, half on success",
                     "at most once per turn"):
        assert required in text
    assert "Exploding Seed" not in text
