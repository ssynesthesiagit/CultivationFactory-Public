"""Owner playtest 2026-10-22, clarity ("that needs to be clearer"): a setting button that read only
"Deadly Strike: off" looked like the talent itself was switched off. It never was: the flat +PB damage while
hidden is the talent's normal effect and applies whichever button is chosen; "off" only meant "do not spend
Martial Focus". The same bare "off" (and one bare "on") appeared on other settings, so every one of them now says
what the choice actually gives you.

These are LABEL tests: option ids are unchanged (saves, AI and condition state still key on them), so each case
also pins the compiled source_definition_id, and the labels are checked where the table builds its menu -- the
compiled action catalog -- not only on the label dictionaries.
"""

from combat.ext.foundation_sacred_body import REBUKE, rebuke_choices
from combat.factory_compiler import compile_character
from tests.test_zones import SHEET

ME = "actor:factory.clarity"
EYE_BASE = "TAL_THE_HIDDEN_EYE_BASE_SPHERE_FEATURES"
BARE = {"", "off", "on", "none", "no"}


def _catalog(*, spheres=(), talents=(), path=()):
    sheet = {**SHEET, "equipment": [],
             "spheres_and_talents": {"sphere_record_ids": list(spheres), "learned_talent_record_ids": list(talents)}}
    if path:
        sheet["path_and_subpath"] = {"path_feature_record_ids": list(path)}
    return compile_character(sheet, actor_id=ME)["action_catalog"]


# feature -> (sheet parts, {expected button label: the effect words that must be in it})
CASES = [
    ("Deadly Strike",
     {"spheres": ["tianxia.sphere.the_hidden_eye"], "talents": [EYE_BASE, "TAL_THE_HIDDEN_EYE_DEADLY_STRIKE"]},
     {"Deadly Strike: normal (+PB damage while hidden, no Martial Focus)": "damage while hidden",
      "Deadly Strike: first hidden attack: spend Martial Focus before rolling; on hit, +PBd6 instead of +PB": "instead of +PB"}),
    ("Adrenaline", {"spheres": ["tianxia.sphere.berserker"], "talents": ["TAL_BERSERKER_BERSERK"]},
     {"Adrenaline: none (no Adrenaline talent, no -2 AC penalty)": "no -2 AC penalty"}),
    ("Deepen the Calamity", {"spheres": ["tianxia.sphere.destruction"], "talents": ["TAL_DESTRUCTION_DESTRUCTIVE_BLAST"]},
     {"Deepen the Calamity: more dice (1 CP a blast: 1 + 1 per 2 Cultivation Levels)": "1 + 1 per 2",
      "Deepen the Calamity: ordinary dice (no extra CP)": "no extra CP"}),
    ("Break the Guard", {"spheres": ["tianxia.sphere.destruction"], "talents": ["tianxia.talent.destruction.break_the_guard"]},
     {"Break the Guard: no Break the Guard effect (Blast Type effects still apply)": "Blast Type effects still apply"}),
    ("Overdraw", {"spheres": ["tianxia.sphere.unmaking"]},
     {"Overdraw: no bonus Ruin damage (no self-damage or Black Vein Strain)": "no bonus Ruin damage"}),
    ("Skewer", {"spheres": ["tianxia.sphere.fencing"],
                "talents": ["TAL_FENCING_SKEWER", "TAL_FENCING_ARM_STRIKE", "TAL_FENCING_SHADOW_STRIKE"]},
     {"Skewer: one only (no Martial Focus spent)": "no Martial Focus spent"}),
    ("Double Dip", {"spheres": ["tianxia.sphere.scoundrel"],
                    "talents": ["TAL_SCOUNDREL_DIRTY_TRICK", "TAL_SCOUNDREL_DOUBLE_DIP"]},
     {"Double Dip: one only (no Martial Focus spent)": "no Martial Focus spent"}),
    ("Exertion", {"spheres": ["tianxia.sphere.berserker"], "talents": ["TAL_BERSERKER_BONE_BREAKER"]},
     {"Exertion: none (no Exertion talent fires on a Batter)": "no Exertion talent"}),
    ("Pressure-Point Strike", {"path": ["tianxia.subpath.body.shinobi.feature.pressure_point_strike"]},
     {"Pressure-Point Strike: don't spend Stamina (no effect)": "don't spend Stamina"}),
    ("Crimson Sacrifice", {"spheres": ["tianxia.sphere.blood"]},
     {"Crimson Sacrifice: pay cultivation resources only (no HP)": "no HP"}),
    ("Vessel construction", {"spheres": ["tianxia.sphere.puppetry"],
                              "talents": ["tianxia.talent.puppetry.ironwood_practice_body"]},
     {"Vessel construction: none (base vessel, no construction bonus)": "no construction bonus",
      "Vessel construction: Guard Body (+2 AC)": "+2 AC"}),
    ("Formation Maneuver",
     {"path": ["tianxia.subpath.qi.banner_cultivator.feature.raise_the_standard",
               "tianxia.subpath.qi.banner_cultivator.feature.advancing_standard"]},
     {"Formation Maneuver: no maneuver (no extra effect)": "no extra effect"}),
]


def test_no_player_visible_option_is_just_off_or_on_and_each_states_its_effect():
    for feature, parts, expected in CASES:
        labels = {row["display_name"] for row in _catalog(**parts) if row["display_name"].startswith(f"{feature}:")}
        assert labels, f"{feature!r} did not compile any menu buttons"
        bare = [label for label in labels if label.split(":", 1)[1].strip().lower() in BARE]
        assert not bare, f"{feature!r} still offers a bare label that reads as the talent being switched off: {bare}"
        for label, effect in expected.items():
            assert label in labels, f"{feature!r}: expected {label!r}, got {sorted(labels)}"
            assert effect in label, f"{feature!r}: {label!r} does not state {effect!r}"


def test_deadly_strike_and_deepen_catalog_keep_their_setting_id_suffixes():
    """Only the display_name moved; the id suffix the choice is stored and read under stays off/empowered/on."""
    deadly = {row["source_definition_id"] for row in _catalog(**CASES[0][1])}
    assert any(source_id.endswith(".deadly_strike.off") for source_id in deadly)
    assert any(source_id.endswith(".deadly_strike.empowered") for source_id in deadly)
    destruction = {row["source_definition_id"] for row in _catalog(**CASES[2][1])}
    assert any(source_id.endswith(".destruction_deepen.off") for source_id in destruction)
    assert any(source_id.endswith(".destruction_deepen.on") for source_id in destruction)


def test_deadly_strike_label_warns_focus_is_paid_before_the_first_attack_not_first_hit():
    actions = _catalog(**CASES[0][1])
    empowered = next(row for row in actions
                     if row["source_definition_id"].endswith(".deadly_strike.empowered"))
    label = empowered["display_name"]
    assert "first hidden attack" in label
    assert "spend Martial Focus before rolling" in label
    assert "on hit, +PBd6 instead of +PB" in label
    assert "first hidden hit" not in label


def test_declining_break_the_guard_label_preserves_blast_type_effects():
    actions = _catalog(**CASES[3][1])
    declined = next(row for row in actions
                    if row["source_definition_id"].endswith(".break_the_guard.off"))
    label = declined["display_name"]
    assert "no Break the Guard effect" in label
    assert "Blast Type effects still apply" in label
    assert "damage only" not in label


def test_saint_body_rebuke_decline_states_what_it_gives_up():
    """Saint-Body Rebuke's own choice, built by its compile hook rather than the catalog (the baseline sheet has no
    foundation feature to compile against)."""
    actions = rebuke_choices({"owned_ids": {REBUKE}, "short": "clarity", "actor_id": ME, "numbers": {}})
    labels = {action.display_name for action in actions}
    assert "Saint-Body Rebuke: don't use it (no Pulse spent, no bonus damage)" in labels
    assert not [label for label in labels if label.split(":", 1)[1].strip().lower() in BARE]
