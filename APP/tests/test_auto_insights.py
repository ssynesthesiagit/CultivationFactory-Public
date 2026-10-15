"""P20261005-13: printed Insights reach a saved fight through their real sheet field.

The lead must regenerate the typed authority before running this module. Positive
cases compile the shipped, hash-bound reviewed rows; no test installs substitute
Insight effects, inserts an Insight into a talent/path field, or changes a lock.

The Ready transport follows test_lock2_persistence: its synthetic option supplies
only deterministic incoming damage/saves/conditions. The owned Insight supplies
the response. This takes that response through preview, accepted table action,
disk reload and mechanical replay, with an otherwise identical non-owner present.
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import zipfile

import pytest

from combat import typed_executor, typed_reactions
from combat.factory_compiler import TYPED_AUTHORITY, compile_character
from combat.gate2_runtime_models import ActionDefinition
from combat.gate5_service import CombatService, FACTORY_ACTOR_PREFIX
from combat.prepared_actions import SOURCE as READY
from combat.tabletop_service import TabletopService
from tests.test_factory_combat_compiler import SHEET
from tests.test_factory_live_match import ROOT
from tests.test_lock2_persistence import act
from tests.test_lock_choices import install


OWNER = FACTORY_ACTOR_PREFIX + "insight-owner"
CONTROL = FACTORY_ACTOR_PREFIX + "insight-control"
PROBE = "test:insights.probe"
HOLD = "system:combat.hold_position"
STAMINA = "resource:core.stamina"
POISONED = "condition:typed.poisoned"

COLD = "insight.cold-star-heart"
FIRE = "insight.furnace-core-survivor"
PSYCHIC = "insight.legacy-soul-ward"
RADIANT = "insight.solar-heart"
FALL_SEVEN = "insight.fall-seven-ways"
ALCHEMICAL = "insight.alchemical-constitution"
HEART_DEMON = "insight.heart-demon-vanquisher"
MOUNTAIN = "insight.mountain-core-stability"
ORGANS = "insight.legacy-tempered-organs"
REPRESENTATIVES = (COLD, FIRE, PSYCHIC, RADIANT, FALL_SEVEN, ALCHEMICAL, HEART_DEMON, MOUNTAIN, ORGANS)


def _sheet(insights=()):
    """Finalized statistics stay identical; Insight ownership has its own surface."""
    sheet = copy.deepcopy(SHEET)
    sheet["spheres_and_talents"] = {
        "sphere_record_ids": [],
        "learned_talent_record_ids": [],
        "cultivation_insight_record_ids": list(insights),
    }
    sheet["equipment"] = []
    return sheet


def _table_match(tmp_path, insight):
    for project, ids in (("insight-owner", [insight]), ("insight-control", [])):
        folder = tmp_path / "portable_characters" / project
        folder.mkdir(parents=True)
        with zipfile.ZipFile(folder / "current.zip", "w") as archive:
            archive.writestr("Tianxia_Owner_Character_Sheet_v1.json", json.dumps(_sheet(ids)))
    combat = CombatService(ROOT, tmp_path)
    combat.tabletop_maps.save({
        "display_name": "Insight yard", "width_squares": 12, "height_squares": 8,
        "walls": [], "starts": {"team1": [[3, 4]], "team2": [[4, 4]]},
    })
    view = combat.create_factory_match(
        project_ids=["insight-owner"], opponent_actor_ids=[CONTROL],
        control_modes={OWNER: "MANUAL", CONTROL: "MANUAL"},
        arena_id="battlefield:map.insight-yard", match_seed="INSIGHT-TABLE:" + insight,
    )
    return combat, TabletopService(combat, tmp_path), view["match_id"]


def _install_probe(monkeypatch, resolve):
    install(monkeypatch, "prepare_options", lambda *args: [{
        "option_id": "insight-probe", "source_id": PROBE,
        "label": "Resolve the incoming test effect", "trigger": "HOLD_POSITION_COMMITTED",
    }])
    install(monkeypatch, "prepared_trigger", lambda *args: True)
    install(monkeypatch, "prepared_action", resolve)


def _commit_probe(combat, table, mid):
    assert act(table, mid, READY)["status"] == "COMMITTED"
    assert act(table, mid, "end")["status"] == "COMMITTED"
    before = combat._load_session(mid).engine.state.model_dump(mode="json")
    pending = act(table, mid, HOLD)
    assert pending["status"] == "REACTION_REQUIRED"
    # A preview may request a reaction, but may not leak damage, a roll or a cost.
    assert combat._load_session(mid).engine.state.model_dump(mode="json") == before
    state, menu = pending["state"], pending["state"]["menu"]
    candidate = next(group["options"][0]["candidate_id"] for group in menu["actions"]
                     if group["source_definition_id"] == HOLD)
    result = table.act(mid, candidate, menu["decision_id"], menu["state_version"], state["last_sequence"],
                       [{**pending["reaction"]["context"], "selection": "USE"}])
    assert result["status"] == "COMMITTED"
    return combat._load_session(mid)


def _reload(tmp_path, mid):
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    assert loaded.mechanical.replay()["status"] == "PASS"
    return loaded


def _insight_rows(engine, actor_id):
    return [row for row in [
        *engine.typed_passive_rows.get(actor_id, []), *engine.typed_reaction_rows.get(actor_id, []),
    ] if str(row.get("feature_id") or "").startswith("insight.")]


def _assert_owner_only(engine, insight):
    assert any(row.get("feature_id") == insight for row in _insight_rows(engine, OWNER))
    assert _insight_rows(engine, CONTROL) == []
    assert not any(str((action.parameters.get("typed") or {}).get("source") or "").startswith("insight.")
                   for action in engine.action_catalog.values() if action.owner_id == CONTROL)


def _damage_rows(engine, who, source):
    return [event.payload for event in engine.events if event.event_type == "DAMAGE_COMMITTED"
            and event.source_definition_id == source and event.target_ids == (who,)]


@pytest.mark.parametrize("insight,damage_type", [
    (COLD, "COLD"), (FIRE, "FIRE"), (PSYCHIC, "PSYCHIC"), (RADIANT, "RADIANT"),
])
def test_printed_resistance_halves_only_its_damage_type_and_survives_table_reload(
        monkeypatch, tmp_path, insight, damage_type):
    """An odd packet rounds down, repeats remain resisted, and Force is unchanged."""
    def resolve(engine, actor, option, event, intent):
        for who in (OWNER, CONTROL):
            subject = engine.state.actors[who]
            aggressor = CONTROL if who == OWNER else OWNER
            for kind in (damage_type, damage_type, "FORCE"):
                engine._commit_damage(subject, 21, kind, PROBE + ":" + kind, aggressor, None, reaction_depth=0)
        return True

    _install_probe(monkeypatch, resolve)
    combat, table, mid = _table_match(tmp_path, insight)
    before = combat._load_session(mid).engine
    _assert_owner_only(before, insight)
    for who, expected in ((OWNER, 0.5), (CONTROL, 1.0)):
        subject = before.state.actors[who]
        assert typed_reactions.damage_factor(before, subject, damage_type, PROBE, None) == expected
        assert typed_reactions.damage_factor(before, subject, "FORCE", PROBE, None) == 1.0

    committed = _commit_probe(combat, table, mid)
    reloaded = _reload(tmp_path, mid)
    for session in (committed, reloaded):
        engine = session.engine
        _assert_owner_only(engine, insight)
        for who, damages in ((OWNER, [10, 10]), (CONTROL, [21, 21])):
            rows = _damage_rows(engine, who, PROBE + ":" + damage_type)
            assert [row["rolled_or_pending_damage"] for row in rows] == [21, 21]
            assert [row["hp_damage"] for row in rows] == damages
            assert [row["hp_damage"] for row in _damage_rows(engine, who, PROBE + ":FORCE")] == [21]
            assert engine.state.actors[who].current_hp == 120 - sum(damages) - 21
            assert typed_reactions.damage_factor(engine, engine.state.actors[who], damage_type, PROBE, None) == (
                0.5 if who == OWNER else 1.0)


def test_mountain_core_shortens_forced_movement_by_ten_feet_once_and_persists_positions(monkeypatch, tmp_path):
    def resolve(engine, actor, option, event, intent):
        for distance in (10, 20):
            for who in (OWNER, CONTROL):
                subject = engine.state.actors[who]
                aggressor = engine.state.actors[CONTROL if who == OWNER else OWNER]
                effect = {"type": "forced_movement", "direction": "away", "distance_ft": distance,
                          "applies_to": "target"}
                typed = {"effects": [effect], "numbers": {"pb": 6, "cl": 17}, "duration": {"kind": "instant"}}
                action = ActionDefinition(
                    source_definition_id=PROBE + f":push:{distance}", display_name="Incoming push stimulus",
                    owner_id=aggressor.entity_id, economy="NONE", resolution_kind="TYPED", target_kind="HOSTILE_ENTITY",
                    range_ft=60, parameters={"typed": typed},
                )
                ctx = typed_executor.Context(engine, aggressor, action, intent, typed, [subject], subject)
                typed_executor.block_forced_movement(ctx, effect)
        return True

    _install_probe(monkeypatch, resolve)
    combat, table, mid = _table_match(tmp_path, MOUNTAIN)
    before = combat._load_session(mid).engine
    _assert_owner_only(before, MOUNTAIN)
    from combat.ext.passive_traits import forced_distance

    assert forced_distance(before, before.state.actors[OWNER], before.state.actors[CONTROL], 20) == 10
    assert forced_distance(before, before.state.actors[CONTROL], before.state.actors[OWNER], 20) is None
    positions = {who: before.state.actors[who].position for who in (OWNER, CONTROL)}
    committed = _commit_probe(combat, table, mid)
    reloaded = _reload(tmp_path, mid)
    for session in (committed, reloaded):
        engine = session.engine
        _assert_owner_only(engine, MOUNTAIN)
        for who, expected in ((OWNER, {10: 0, 20: 10}), (CONTROL, {10: 10, 20: 20})):
            for requested, travelled in expected.items():
                rows = [event for event in engine.events if event.event_type == "MOVEMENT_COMMITTED"
                        and event.actor_id == who and event.source_definition_id == PROBE + f":push:{requested}"]
                assert sum((len(row.payload["path"]) - 1) * 5 for row in rows) == travelled
                assert all(row.payload["forced"] and row.payload["cost_ft"] == 0 for row in rows)
            assert engine.grid.distance_ft(positions[who], engine.state.actors[who].position) == sum(expected.values())
            assert engine.state.actors[who].movement_remaining_ft == 30


def test_fall_seven_ways_stands_for_five_feet_while_non_owner_pays_half_speed_after_reload(monkeypatch, tmp_path):
    from combat import posture

    def resolve(engine, actor, option, event, intent):
        for who in (OWNER, CONTROL):
            engine._apply_condition(engine.state.actors[who], "condition:typed.prone", PROBE,
                                    CONTROL if who == OWNER else OWNER, expires_on="STAND_UP")
        return True

    _install_probe(monkeypatch, resolve)
    combat, table, mid = _table_match(tmp_path, FALL_SEVEN)
    _commit_probe(combat, table, mid)
    prone = _reload(tmp_path, mid).engine
    _assert_owner_only(prone, FALL_SEVEN)
    assert posture.standing_cost(prone, prone.state.actors[OWNER]) == 5
    assert posture.standing_cost(prone, prone.state.actors[CONTROL]) == 15
    current_id = table.state(mid)["menu"]["actor_id"]
    current = prone.state.actors[current_id]
    economy_before = (current.action_available, current.bonus_action_available, current.reaction_available)
    assert act(table, mid, posture.SOURCE)["status"] == "COMMITTED"
    standing = _reload(tmp_path, mid).engine
    stood = standing.state.actors[current_id]
    assert not posture.prone_conditions(stood)
    assert (stood.action_available, stood.bonus_action_available, stood.reaction_available) == economy_before
    # The other creature then stands through the same production transition at its
    # ordinary turn start; this proves both sides pay the correct persisted cost.
    assert act(table, mid, "end")["status"] == "COMMITTED"
    committed = combat._load_session(mid)
    reloaded = _reload(tmp_path, mid)
    for session in (committed, reloaded):
        engine = session.engine
        _assert_owner_only(engine, FALL_SEVEN)
        for who, expected in ((OWNER, 5), (CONTROL, 15)):
            rows = [event.payload for event in engine.events if event.event_type == "STOOD_UP" and event.actor_id == who]
            assert len(rows) == 1
            assert rows[0]["cost_ft"] == expected
            assert rows[0]["movement_before"] == 30 and rows[0]["movement_after"] == 30 - expected
            assert engine.state.actors[who].movement_remaining_ft == 30 - expected
            assert not posture.prone_conditions(engine.state.actors[who])


def _save_effect(threat, ability):
    if threat.startswith("damage:"):
        failed = {"type": "damage", "flat": 1, "damage_types": [threat.split(":", 1)[1]], "applies_to": "target"}
    elif threat == "forced_movement":
        failed = {"type": "forced_movement", "kind": "push", "distance_ft": 5, "applies_to": "target"}
    else:
        failed = {"type": "condition", "condition": threat, "applies_to": "target"}
    return {"type": "save", "ability": ability, "on_fail": [failed], "on_success": []}


def _save_context(engine, who, threat, ability, intent=None):
    subject = engine.state.actors[who]
    aggressor = engine.state.actors[CONTROL if who == OWNER else OWNER]
    effect = _save_effect(threat, ability)
    # DC 1 permits every fixture save to succeed, so a previous test threat never
    # supplies a condition that could alter the next save's mode. We test Advantage,
    # not the random success/failure of a particular seeded d20.
    typed = {"effects": [effect], "numbers": {"pb": 6, "cl": 17, "save_dc": 1}, "duration": {"kind": "instant"}}
    action = ActionDefinition(
        source_definition_id=PROBE + ":save:" + threat, display_name="Incoming save stimulus",
        owner_id=aggressor.entity_id, economy="NONE", resolution_kind="TYPED", target_kind="HOSTILE_ENTITY",
        range_ft=30, parameters={"typed": typed},
    )
    return typed_executor.Context(engine, aggressor, action, intent, typed, [subject], subject), effect


@pytest.mark.parametrize("insight,ability,eligible,unrelated", [
    (ALCHEMICAL, "CON", ("poisoned", "damage:poison"), "frightened"),
    (HEART_DEMON, "WIS", ("charmed", "frightened"), "poisoned"),
    (MOUNTAIN, "STR", ("forced_movement", "prone"), "blinded"),
])
def test_printed_save_advantage_is_scoped_to_its_owner_and_threat_after_reload(
        monkeypatch, tmp_path, insight, ability, eligible, unrelated):
    threats = (*eligible, unrelated)

    def resolve(engine, actor, option, event, intent):
        for who in (OWNER, CONTROL):
            for threat in threats:
                ctx, effect = _save_context(engine, who, threat, ability, intent)
                typed_executor.block_save(ctx, effect)
        return True

    _install_probe(monkeypatch, resolve)
    combat, table, mid = _table_match(tmp_path, insight)
    before = combat._load_session(mid).engine
    _assert_owner_only(before, insight)
    for who in (OWNER, CONTROL):
        for threat in threats:
            ctx, effect = _save_context(before, who, threat, ability)
            shaped, _, _, _ = typed_executor.typed_save_modifiers(
                ctx, before.state.actors[who], ability, effect["on_fail"], effect["on_success"])
            assert ("ADVANTAGE" in shaped["modes"]) is (who == OWNER and threat in eligible)

    committed = _commit_probe(combat, table, mid)
    reloaded = _reload(tmp_path, mid)
    for session in (committed, reloaded):
        engine = session.engine
        _assert_owner_only(engine, insight)
        for who in (OWNER, CONTROL):
            for threat in threats:
                rows = [event.payload for event in engine.events if event.event_type == "SAVE_ROLLED"
                        and event.actor_id == who and event.source_definition_id == PROBE + ":save:" + threat]
                assert len(rows) == 1
                expected = "ADVANTAGE" if who == OWNER and threat in eligible else "NORMAL"
                assert rows[0]["mode"] == expected
                assert len(rows[0]["dice"]) == (2 if expected == "ADVANTAGE" else 1)
                assert rows[0]["success"] is True


def _feature_actions(engine, who, insight):
    return [action for action in engine.action_catalog.values() if action.owner_id == who
            and (action.parameters.get("typed") or {}).get("source") == insight]


def _has_poison(engine, who):
    return any(condition.condition_id == POISONED for condition in engine.state.actors[who].conditions.values())


def test_tempered_organs_bonus_action_spends_two_stamina_and_removes_only_owners_poison(monkeypatch, tmp_path):
    def resolve(engine, actor, option, event, intent):
        for who in (OWNER, CONTROL):
            engine._apply_condition(engine.state.actors[who], POISONED, PROBE, CONTROL if who == OWNER else OWNER,
                                    expires_on="UNTIL_REMOVED")
        return True

    _install_probe(monkeypatch, resolve)
    combat, table, mid = _table_match(tmp_path, ORGANS)
    before = combat._load_session(mid).engine
    _assert_owner_only(before, ORGANS)  # its independent Poison resistance also compiles
    owner_actions = _feature_actions(before, OWNER, ORGANS)
    assert len(owner_actions) == 1
    action_id = owner_actions[0].source_definition_id
    assert str(owner_actions[0].economy) == "BONUS_ACTION"
    assert dict(owner_actions[0].costs) == {STAMINA: 2}
    assert _feature_actions(before, CONTROL, ORGANS) == []

    _commit_probe(combat, table, mid)
    poisoned = _reload(tmp_path, mid)
    assert _has_poison(poisoned.engine, OWNER) and _has_poison(poisoned.engine, CONTROL)
    # Initiative is irrelevant: use the real end-turn action until the owner can act.
    for _ in range(2):
        if table.state(mid)["menu"]["actor_id"] == OWNER:
            break
        assert act(table, mid, "end")["status"] == "COMMITTED"
    assert table.state(mid)["menu"]["actor_id"] == OWNER
    current = combat._load_session(mid).engine.state.actors[OWNER]
    action_available = current.action_available
    assert current.resources[STAMINA] == 40 and current.bonus_action_available
    assert act(table, mid, action_id)["status"] == "COMMITTED"

    committed = combat._load_session(mid)
    reloaded = _reload(tmp_path, mid)
    for session in (committed, reloaded):
        engine = session.engine
        _assert_owner_only(engine, ORGANS)
        assert not _has_poison(engine, OWNER)
        assert _has_poison(engine, CONTROL)
        assert engine.state.actors[OWNER].resources[STAMINA] == 38
        assert engine.state.actors[CONTROL].resources[STAMINA] == 40
        assert not engine.state.actors[OWNER].bonus_action_available
        assert engine.state.actors[OWNER].action_available == action_available
        assert _feature_actions(engine, CONTROL, ORGANS) == []
        removed = [event for event in engine.events if event.event_type == "CONDITION_REMOVED"
                   and event.source_definition_id == action_id and event.payload.get("condition_id") == POISONED]
        assert len(removed) == 1


def test_insights_do_not_reapply_ability_increases_or_other_finalized_sheet_statistics():
    plain = _sheet()
    owned = _sheet(REPRESENTATIVES)
    stats_before = copy.deepcopy(owned["ability_scores_and_statistics"])
    baseline = compile_character(plain, actor_id=OWNER)["actor_template"]
    compiled = compile_character(owned, actor_id=OWNER)["actor_template"]
    assert owned["ability_scores_and_statistics"] == stats_before
    for key in ("armor_class", "maximum_hp", "speed_ft", "initiative_bonus", "dexterity_score", "strength_score",
                "proficiency_bonus", "saving_throws", "resources"):
        assert compiled[key] == baseline[key], key


@pytest.fixture(scope="module")
def insight_authority():
    """Read the lead-generated authority; never generate or replace it in a test."""
    return json.loads(TYPED_AUTHORITY.read_bytes())


def _authored_insight_finals(root):
    """Census Insight rows in every reviewed source, independently of the generator."""
    reviewed = root / "authority/typed_mechanics"
    paths = ([reviewed / "reviewed_final.json"] if (reviewed / "reviewed_final.json").is_file() else [])
    paths += sorted((reviewed / "reviewed_final.d").glob("*.json"))
    finals = {}
    for path in paths:
        document = json.loads(path.read_bytes())
        for key, row in document["mechanics"].items():
            if not key.startswith("insight."):
                continue
            assert document["schema"] == "TianxiaFoundry.ReviewedFinalMechanics.v1", path.name
            assert key not in finals, (path.name, key)
            finals[key] = row
    assert finals, "The authored Insight reviews must be present"
    return finals


@pytest.fixture(scope="module")
def authored_insight_finals():
    """Read authored source files without importing or invoking the generator."""
    return _authored_insight_finals(ROOT)


@pytest.mark.parametrize("relative_path", ["reviewed_final.json", "reviewed_final.d/mixed_sphere_review.json"])
def test_insight_review_census_discovers_mixed_sources_without_a_filename_prefix(tmp_path, relative_path):
    # Use Ink's real mixed talent/Insight review bytes, including its authored
    # effects. Both supported source locations must contribute to the census.
    source = ROOT / "authority/typed_mechanics/reviewed_final.d/auto138_ink.json"
    destination = tmp_path / "authority/typed_mechanics" / relative_path
    destination.parent.mkdir(parents=True)
    destination.write_bytes(source.read_bytes())
    # Legacy non-Insight reviews have other schemas. Their metadata must not
    # prevent discovery or relax the schema requirement for an Insight review.
    unrelated = tmp_path / "authority/typed_mechanics/reviewed_final.d/legacy_talents.json"
    unrelated.parent.mkdir(parents=True, exist_ok=True)
    unrelated.write_bytes((ROOT / "authority/typed_mechanics/reviewed_final.d/auto11_scoundrel.json").read_bytes())
    expected = {key: row for key, row in json.loads(source.read_bytes())["mechanics"].items()
                if key.startswith("insight.")}
    assert expected
    assert _authored_insight_finals(tmp_path) == expected


def test_generated_insights_preserve_every_authored_final_field(insight_authority, authored_insight_finals):
    # This list is deliberately independent of the generator's implementation.
    # None means absence/null at authority level; all other authored values,
    # including empty containers and nested modifier costs, survive verbatim.
    fields = ("effects", "options", "modifier", "activation", "riders", "range", "area", "cost",
              "use_limit", "duration", "target", "after", "min_cp_cost")
    empty_modifier_costs = set()
    for key, final in authored_insight_finals.items():
        generated = insight_authority["mechanics"][key]
        assert generated["typing_status"] == "reviewed_final", key
        assert generated["insight_reviewed_text_sha256"] == final["text_sha256"], key
        assert all(field in final for field in fields), key
        for field in (*fields, "weapon_delivery", "reaction_target"):
            if field not in final:
                continue
            # Serialized equality distinguishes JSON false from 0 and preserves
            # nested arrays/types as well as the values; object-key order is free.
            assert json.dumps(generated.get(field), sort_keys=True) == json.dumps(final[field], sort_keys=True), (key, field)
        modifier = final.get("modifier")
        if isinstance(modifier, dict) and modifier.get("cost") == []:
            empty_modifier_costs.add(key)
            assert "cost" in generated["modifier"], key
            assert generated["modifier"]["cost"] == [], key
    assert empty_modifier_costs, "An authored empty modifier.cost must exercise the no-inherited-cost regression"


def test_unreviewed_insights_remain_manual_without_effects_options_modifiers_or_review_hash(
        insight_authority, authored_insight_finals):
    from factory_authoring.insight_sources import current_insight_sources

    current = current_insight_sources(ROOT)
    unreviewed = set(current) - set(authored_insight_finals)
    assert unreviewed, "The census contains intentionally manual Insights"
    for key in sorted(unreviewed):
        row = insight_authority["mechanics"][key]
        assert row["effects"] == [], key
        assert row.get("options") in (None, []), key
        assert row.get("modifier") in (None, {}), key
        assert row["typing_status"] == "manual_review_required", key
        assert row["coverage"] == "RIDERS_ONLY", key
        assert "insight_reviewed_text_sha256" not in row, key
        assert current[key]["text"] in row["riders"], key


def test_every_canonical_printed_insight_has_source_bound_typed_authority(insight_authority):
    from factory_authoring.insight_sources import SOURCE_PATH, current_insight_sources

    source_document = json.loads((ROOT / SOURCE_PATH).read_bytes())
    expected = {row["canonical_id"] for row in source_document["records"]}
    actual = {key for key in insight_authority["mechanics"] if key.startswith("insight.")}
    assert actual == expected
    current = current_insight_sources(ROOT)
    assert set(current) == expected
    for key in sorted(expected):
        row, source = insight_authority["mechanics"][key], current[key]
        assert row["kind"] == "cultivation_insight", key
        assert row["insight_selectable"] is source["insight_selectable"], key
        for field in ("record_id", "record_sha256", "text_sha256"):
            assert row["source"][field] == source["source"][field], (key, field)
        assert row["source"]["text_sha256"] == hashlib.sha256(source["text"].encode("utf-8")).hexdigest()
        if row.get("insight_reviewed_text_sha256"):
            assert row["insight_reviewed_text_sha256"] == row["source"]["text_sha256"], key
    for key in REPRESENTATIVES:
        row = insight_authority["mechanics"][key]
        assert row["typing_status"] == "reviewed_final", key
        assert row["insight_reviewed_text_sha256"] == row["source"]["text_sha256"], key


def _bundle_has_insight(bundle, insight):
    return (any(row.get("feature_id") == insight for row in [*bundle["typed_passives"], *bundle["typed_reactions"]])
            or any((row.get("parameters", {}).get("typed") or {}).get("source") == insight
                   for row in bundle["action_catalog"])
            or any(row.get("id") == insight and row.get("status") == "applied" for row in bundle["modifiers"]))


def _boundary(bundle, insight):
    """The compiled automation boundary the sheet library shows for one owned Insight."""
    return next(row for row in (bundle.get("diagnostics") or {}).get("insights") or [] if row["id"] == insight)


@pytest.mark.parametrize("field,value", [
    ("kind", "talent"), ("insight_selectable", False),
    ("typing_status", "parser"), ("insight_reviewed_text_sha256", "0" * 64),
    ("source.text_sha256", "0" * 64), ("source.record_sha256", "0" * 64),
])
def test_stale_unreviewed_or_nonselectable_insight_cannot_activate_a_feature_block(insight_authority, field, value):
    # Negative corruption only: the positive comparison uses the actual generated
    # Cold-Star record and source hash. No invented mechanical effect is admitted.
    sheet = _sheet([COLD])
    assert _bundle_has_insight(compile_character(sheet, actor_id=OWNER), COLD)
    authority = copy.deepcopy(insight_authority)
    row = authority["mechanics"][COLD]
    if field.startswith("source."):
        row["source"][field.split(".", 1)[1]] = value
    else:
        row[field] = value
    rejected = compile_character(sheet, actor_id=OWNER, typed_authority=authority)
    assert not _bundle_has_insight(rejected, COLD)
    from factory_authoring.insight_sources import current_insight_sources

    current_text = current_insight_sources(ROOT)[COLD]["text"]
    # The machine id moved out of the player-readable note into the structured
    # boundary row (checklist 13); the note keeps the printed rule and the reason.
    assert _boundary(rejected, COLD)["status"] == "manual"
    assert any("Cold Star Heart" in note and "Manual rules:" in note and current_text in note
               for note in rejected["diagnostics"]["notes"])


def test_stale_feature_block_is_not_rescued_by_a_current_insight_record(monkeypatch):
    assert _bundle_has_insight(compile_character(_sheet([COLD]), actor_id=OWNER), COLD)
    rules = copy.deepcopy(typed_reactions.rules())
    rules["features"][COLD]["text_sha256"] = "0" * 64
    monkeypatch.setattr(typed_reactions, "rules", lambda: rules)
    assert not _bundle_has_insight(compile_character(_sheet([COLD]), actor_id=OWNER), COLD)


def test_duplicate_owned_insight_ids_compile_one_benefit_and_unknown_id_stays_manual():
    once = compile_character(_sheet([COLD]), actor_id=OWNER)
    repeated = _sheet([COLD, COLD])
    repeated["spheres_and_talents"]["cultivation_insight_occurrences"] = [
        {"record_id": COLD, "occurrence_id": "advancement:one"},
        {"record_id": COLD, "occurrence_id": "advancement:two"},
    ]
    twice = compile_character(repeated, actor_id=OWNER)
    assert [row for row in twice["typed_passives"] if row.get("feature_id") == COLD] == [
        row for row in once["typed_passives"] if row.get("feature_id") == COLD]
    assert len([row for row in twice["typed_passives"] if row.get("feature_id") == COLD]) == 1
    occurrences_only = _sheet()
    occurrences_only["spheres_and_talents"]["cultivation_insight_occurrences"] = [
        {"record_id": COLD, "occurrence_id": "advancement:one"},
    ]
    assert _bundle_has_insight(compile_character(occurrences_only, actor_id=OWNER), COLD)
    unknown = "insight.no-such-printed-insight"
    unresolved = compile_character(_sheet([unknown]), actor_id=OWNER)
    assert not _bundle_has_insight(unresolved, unknown)
    assert _boundary(unresolved, unknown)["status"] == "manual"
    assert any("Manual rules:" in note for note in unresolved["diagnostics"]["notes"])
    assert not any(unknown in note for note in unresolved["diagnostics"]["notes"])  # no internal id in player text


def test_source_edit_with_unchanged_timestamp_invalidates_review_and_preserves_new_manual_text(monkeypatch, tmp_path):
    from factory_authoring import insight_sources

    assert _bundle_has_insight(compile_character(_sheet([COLD]), actor_id=OWNER), COLD)
    source_path = tmp_path / insight_sources.SOURCE_PATH
    source_path.parent.mkdir(parents=True)
    source_path.write_bytes((ROOT / insight_sources.SOURCE_PATH).read_bytes())
    read_current = insight_sources.current_insight_sources
    original = read_current(tmp_path)[COLD]
    timestamp = source_path.stat()
    document = json.loads(source_path.read_bytes())
    selected = next(row for row in document["records"] if row.get("record_id") == original["source"]["record_id"])
    changed_text = selected["full_rules_text"] + "\nOwner edit pending renewed combat review."
    selected["full_rules_text"] = changed_text
    source_path.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")
    os.utime(source_path, ns=(timestamp.st_atime_ns, timestamp.st_mtime_ns))
    assert source_path.stat().st_mtime_ns == timestamp.st_mtime_ns
    changed = read_current(tmp_path)[COLD]
    assert changed["source"]["text_sha256"] != original["source"]["text_sha256"]
    assert changed["source"]["record_sha256"] != original["source"]["record_sha256"]
    # Authority and feature-block bytes are unchanged; only their live printed
    # source has changed. Admission must still stop before either benefit runs.
    monkeypatch.setattr(insight_sources, "current_insight_sources", lambda app: read_current(tmp_path))
    rejected = compile_character(_sheet([COLD]), actor_id=OWNER)
    assert not _bundle_has_insight(rejected, COLD)
    assert any("Cold Star Heart" in note and "Manual rules:" in note and changed_text in note
               for note in rejected["diagnostics"]["notes"])


# --- The table tells the player how far each Insight got (PRO13 review findings 1 and 2) ---
# The library used to answer "info / not a combat rule" for every Insight, so an
# automated Cold resistance, a partly implemented Insight and one the fight rejects
# all looked identical. These read the real TabletopService.sheet response.
PID = "abcdef12"
_BOUNDARY_JARGOON = re.compile(
    r"\b(?:compiler|interpreter|plug-?in|seams?|hook)\b|\.py\b|\bcombat/|\b(?:condition|resource|action|event|flag):[a-z_]"
    r"|\btyped\.[a-z_]|insight\.[a-z]"
    # Implementation explanations a reviewer wrote and a player must not read. "hook" is
    # deliberately absent: a grappling hook and Soul Hook are the setting's own words.
    r"|\btyped\b|\bcategor(?:y|ies|ise|ised)\b|\bqualification\b|\bqualifying\b|\bpredicate\b"
    r"|\bprovenance\b|\binterception\b|\bbindings?\b|\bautomated\b|\bautomation\b",
    re.I)


def _install_portable(tmp_path, sheet, pid=PID):
    folder = tmp_path / "portable_characters" / pid
    folder.mkdir(parents=True)
    with zipfile.ZipFile(folder / "current.zip", "w") as archive:
        archive.writestr("Tianxia_Owner_Character_Sheet_v1.json", json.dumps(sheet))


def _library_insights(tmp_path, insights):
    from factory_authoring.insight_sources import current_insight_sources

    names = {key: (current_insight_sources(ROOT).get(key) or {}).get("name") or key for key in insights}
    sheet = _sheet(insights)
    sheet["selected_record_sections"] = {"insights": [
        {"record_id": key, "display_name": names[key], "full_description": "The printed Insight text."}
        for key in insights]}
    _install_portable(tmp_path, sheet)
    payload = TabletopService(CombatService(ROOT, tmp_path), tmp_path).sheet(PID)
    return {row["id"]: row for row in
            next(group for group in payload["library"]["groups"] if group["key"] == "insights")["entries"]}


def test_the_sheet_library_separates_automated_partial_and_rejected_insights(tmp_path):
    rejected = "insight.no-such-printed-insight"
    entries = _library_insights(tmp_path, [COLD, FALL_SEVEN, rejected])
    # Cold Star Heart now runs all its combat clauses. The 5-foot stand remains
    # partial and must still print the clauses that its review leaves manual.
    assert entries[COLD]["status"] == "auto" and entries[FALL_SEVEN]["status"] == "partial"
    assert "Cold damage is halved" in entries[COLD]["automation"]
    assert "ignore" in entries[COLD]["automation"] and "Immunity" in entries[COLD]["automation"]
    assert "standing up from Prone costs 5 feet of your movement" in entries[FALL_SEVEN]["automation"]
    assert "Nothing about it is left for your Game Master" in entries[COLD]["automation"]
    assert "Game Master" in entries[FALL_SEVEN]["automation"]
    # A rejected Insight is a fight rule the table skips, not reference reading.
    assert entries[rejected]["status"] == "gm"
    assert "is not run by the fight table" in entries[rejected]["automation"]


def test_an_insight_with_nothing_left_manual_is_reported_as_fully_automated(tmp_path, insight_authority):
    """A partial Insight becomes automated when its remaining clauses are removed.

    Fall Seven Ways retains real residual clauses; Cold Star Heart is now fully
    automated in the shipped authority, so it is no longer the partial fixture.
    """
    authority = copy.deepcopy(insight_authority)
    assert authority["mechanics"][FALL_SEVEN]["riders"]
    authority["mechanics"][FALL_SEVEN]["riders"] = []
    boundary = _boundary(compile_character(_sheet([FALL_SEVEN]), actor_id=OWNER, typed_authority=authority), FALL_SEVEN)
    assert boundary["gm_decides"] == [] and boundary["status"] == "automated"
    entry = _library_insights(tmp_path, [FALL_SEVEN])[FALL_SEVEN]
    # The shipped record still carries riders, so the sheet keeps the partial status
    # the automated table grants it; the fully automatic wording is asserted below.
    assert entry["status"] == "partial"
    assert _boundary(compile_character(_sheet([FALL_SEVEN]), actor_id=OWNER, typed_authority=authority), FALL_SEVEN)["explanation"].endswith(
        "Nothing about it is left for your Game Master.")


def test_every_owned_insight_boundary_is_plain_words_and_names_what_the_table_runs():
    """Checklist 13: the sheet line may not leak an id, a file name or a build word."""
    bundle = compile_character(_sheet([*REPRESENTATIVES, "insight.no-such-printed-insight"]), actor_id=OWNER)
    assert _boundary(bundle, "insight.no-such-printed-insight")["status"] == "manual"
    for row in bundle["diagnostics"]["insights"]:
        assert not _BOUNDARY_JARGOON.search(row["explanation"]), row
        assert row["table_applies"] or row["gm_decides"], row
    # Every owned Insight has a boundary, so nothing can silently read as "Reference".
    assert {row["id"] for row in bundle["diagnostics"]["insights"]} == {*REPRESENTATIVES, "insight.no-such-printed-insight"}


def test_a_boundary_never_asks_the_game_master_to_rule_on_something_it_says_the_table_runs(tmp_path):
    """Review finding 1: the boundary listed the informational rider beside the manual one.

    Tempered Organs' own review said Poison Resistance and Advantage against Poisoned or
    Poison damage are applied by the fight. Carried as a manual clause the sheet told the
    Game Master to rule on the very defenses the sentence above had called automatic. A
    reviewer's ``notes`` are what they recorded *about* the record; only ``riders`` are
    clauses to rule. This reads the real service response for that record.
    """
    boundary = _boundary(compile_character(_sheet([ORGANS]), actor_id=OWNER), ORGANS)
    automatic = " ".join(boundary["table_applies"]).lower()
    assert "poison" in automatic, boundary["table_applies"]
    manual = " ".join(boundary["gm_decides"]).lower()
    assert "poison resistance" not in manual, boundary["gm_decides"]
    assert "typed saves" not in manual, boundary["gm_decides"]
    # The clause the review really left manual is still there, and still offered.
    assert "disease" in manual and "impair breathing" in manual, boundary["gm_decides"]
    # What the reviewer recorded about the record is kept, but out of the manual list.
    assert any("applied by the fight itself" in note for note in boundary["notes"]), boundary["notes"]
    entry = _library_insights(tmp_path, [ORGANS])[ORGANS]
    assert entry["status"] == "partial"
    assert "poison resistance" not in entry["automation"].lower(), entry["automation"]
    assert "Disease" in entry["automation"], entry["automation"]
    assert not _BOUNDARY_JARGOON.search(entry["automation"]), entry["automation"]


def test_a_rejected_insight_says_why_it_was_rejected_through_the_service(tmp_path, insight_authority):
    """Review finding 2: the rejection reason was built and then overwritten.

    A stale reviewed source stops the Insight, but the sentence the player reads used to
    say only "not run by the fight table", so a previously working Insight and an
    unreviewed one read the same. The reason now survives into the sheet entry, through
    the real service, for a source hash that no longer matches.
    """
    authority = copy.deepcopy(insight_authority)
    authority["mechanics"][COLD]["source"]["text_sha256"] = "0" * 64
    _install_portable(tmp_path, _sheet([COLD]))
    bundle = compile_character(_sheet([COLD]), actor_id=OWNER, typed_authority=authority)
    rejected = _boundary(bundle, COLD)
    assert rejected["status"] == "manual" and rejected["table_applies"] == []
    assert "its rules have changed since they were last checked" in rejected["explanation"], rejected
    assert not _BOUNDARY_JARGOON.search(rejected["explanation"]), rejected
    # The manual rules still come with it, so the Game Master has something to rule from.
    assert rejected["gm_decides"] and rejected["gm_decides"] != [""], rejected


def test_a_stale_source_rejection_reaches_the_sheet_response(tmp_path, insight_authority):
    """The same reason read from the service rather than from the compiler's own dict.

    The whole path is the real one: the service compiles the character from its portable
    copy and the sheet library reads the bundle it produced. Only the *authority the
    compiler reads* is a stale copy, written to this test's own folder, so the saved
    inspection on disk is untouched.
    """
    import combat.factory_compiler as compiler

    stale = copy.deepcopy(insight_authority)
    stale["mechanics"][COLD]["source"]["text_sha256"] = "0" * 64
    path = tmp_path / "stale-authority.json"
    path.write_bytes(json.dumps(stale).encode("utf-8"))
    sheet = _sheet([COLD])
    sheet["selected_record_sections"] = {"insights": [
        {"record_id": COLD, "display_name": "Cold Star Heart", "full_description": "The printed Insight text."}]}
    _install_portable(tmp_path, sheet)
    original = compiler.TYPED_AUTHORITY
    compiler.TYPED_AUTHORITY = path
    try:
        payload = TabletopService(CombatService(ROOT, tmp_path), tmp_path).sheet(PID)
    finally:
        compiler.TYPED_AUTHORITY = original
    entry = next(row for row in next(group for group in payload["library"]["groups"]
                                     if group["key"] == "insights")["entries"] if row["id"] == COLD)
    assert entry["status"] == "gm", entry
    assert "its rules have changed since they were last checked" in entry["automation"], entry
    assert not _BOUNDARY_JARGOON.search(entry["automation"]), entry
    # The automatic reading is gone with the effect: no benefit is claimed at all.
    assert "damage of type Cold is halved" not in entry["automation"], entry


def test_a_character_without_insights_keeps_the_diagnostics_it_had():
    plain = compile_character(_sheet(), actor_id=OWNER)
    assert "insights" not in plain["diagnostics"]
    assert set(plain["diagnostics"]) == {"skipped", "notes"}
