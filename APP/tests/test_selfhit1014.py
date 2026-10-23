"""Area recipient policy at geometry, reaction and cold table reload boundaries."""
import pytest

from combat.area_recipients import scoped_area, harmful_area_subject_allowed
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from combat.typed_executor import _area_targets
from tests.h1_support import ROOT
from tests.test_area_shapes import _Actor, _Engine
from tests.test_friendly_fire_area_table import _commit_area_action
from tests.test_tabletop_hunt6 import LEFT, ALLY, RIGHT, table_fight

BREATH = "TAL_DAEMONIC_CULTIVATION_HUNGER_REFINING_BREATH"
AUGMENT = "TAL_DAEMONIC_CULTIVATION_DAEMONIC_AUGMENT"
GUARD = "tianxia.path.body_refining.feature.stamina_guard"


@pytest.mark.parametrize("scope", ["hostile", "enemies_in_area"])
def test_enemy_area_never_admits_its_caster_even_with_include_self(scope):
    user, ally, enemy = _Actor("user", "a", 3, 4), _Actor("ally", "a", 4, 4), _Actor("enemy", "b", 5, 4)
    area = {"shape": "cone", "size_ft": 30, "recipients": scope, "include_self": True}
    assert _area_targets(_Engine([user, ally, enemy]), user, enemy.position, area) == [enemy]


@pytest.mark.parametrize("wording,inclusive", [
    ("Creatures in the cone make Constitution saving throws.", False),
    ("Each creature in the cone makes a Constitution saving throw.", True),
    ("Every creature in the cone makes a Constitution saving throw.", True),
])
def test_printed_scope_replaces_obsolete_geometry_and_bounds_packets(wording, inclusive):
    effect = {"type": "save", "applies_to": "creatures_in_area", "recipient_text": wording,
              "on_fail": [{"type": "damage", "flat": 17, "applies_to": "creatures_in_area"}]}
    area = scoped_area({"shape": "cone", "size_ft": 30, "recipients": "all",
                        "include_self": True, "exclude_self": False}, [effect])
    user, ally, enemy = _Actor("user", "a", 3, 4), _Actor("ally", "a", 4, 4), _Actor("enemy", "b", 5, 4)
    # An origin cone never catches its user, even with inclusive wording.
    expected = [ally, enemy] if inclusive else [enemy]
    assert _area_targets(_Engine([user, ally, enemy]), user, enemy.position, area) == expected
    assert [a for a in [user, ally, enemy] if harmful_area_subject_allowed(user, a, area, effect)] == expected


def test_other_creatures_scope_excludes_user_and_delayed_scope_keeps_printed_policy():
    from types import SimpleNamespace
    from combat.area_recipients import delayed_area_context
    effect = {"type": "damage", "flat": 4, "evidence": "Each other creature takes damage."}
    area = scoped_area({"shape": "sphere", "size_ft": 15}, [effect])
    assert area["recipients"] == "all" and area["exclude_self"] and not area["include_self"]
    user, ally, enemy = _Actor("user", "a", 3, 4), _Actor("ally", "a", 3, 5), _Actor("enemy", "b", 4, 4)
    assert _area_targets(_Engine([user, ally, enemy]), user, user.position, area) == [ally, enemy]
    action = SimpleNamespace(parameters={"typed": {"area": area, "source": "test:printed-zone"}})
    engine = SimpleNamespace(action_catalog={"test:printed-zone": action})
    zone = SimpleNamespace(source_definition_id="test:printed-zone", trigger_profile={})
    context = delayed_area_context(engine, zone, [{"type": "damage", "flat": 4}])
    assert context["area"]["explicit_harmful_recipients"] == "other_creatures"


def test_transient_parent_area_scope_is_inert_for_non_area_payloads():
    from types import SimpleNamespace
    from combat.typed_executor import _declared_subjects
    user, ally, enemy = _Actor("user", "a", 3, 4), _Actor("ally", "a", 3, 5), _Actor("enemy", "b", 4, 4)
    effect = {"type": "damage", "flat": 3, "applies_to": "enemies_in_area"}
    ctx = SimpleNamespace(actor=user, target=None, targets=[user, ally, enemy],
                          typed={"effects": [effect]}, area_harmful_scope="all")
    assert _declared_subjects(ctx, effect, harmful=True) == [enemy]


@pytest.mark.parametrize("augmented", [False, True])
def test_own_breath_only_harms_enemies_after_table_commit_and_cold_reload(tmp_path, augmented):
    talents = [BREATH, GUARD] + ([AUGMENT] if augmented else [])
    combat, table, mid = table_fight(tmp_path, talents, cl=10, ask=True, ally_talents=[], primary="Stamina",
        starts={"team1": [[3, 4], [4, 4]], "team2": [[5, 4]]})
    groups = [g for g in table.state(mid)["menu"]["actions"] if BREATH in g["source_definition_id"]
              and (("Daemonic Augment: Bonus Damage" in g["label"]) if augmented
                   else "Daemonic Augment" not in g["label"])]
    group = min(groups, key=lambda g: len(g["label"]))
    label = group["label"]
    action = combat._load_session(mid).engine.action_catalog[group["source_definition_id"]]
    assert ("resource:core.stamina", 3 if augmented else 2) in action.costs
    before = combat._load_session(mid).engine.state.model_dump(mode="json")
    assert any(row["feature_id"] == GUARD for row in combat._load_session(mid).engine.typed_reaction_rows[LEFT])
    result, option = _commit_area_action(table, mid, label, {"x": 5, "y": 4})
    answers = []
    for _ in range(24):
        if result["status"] == "COMMITTED":
            break
        assert result["status"] == "REACTION_REQUIRED", result
        prompt = result["reaction"]
        assert not (prompt["context"]["reactor_id"] == LEFT and
                    "stamina_guard" in prompt["context"]["reaction_source_id"]), prompt
        answers.append({**prompt["context"], "selection": "DECLINE"})
        table = TabletopService(CombatService(ROOT, tmp_path), tmp_path)
        state = table.state(mid)
        result = table.act(mid, option["candidate_id"], state["menu"]["decision_id"],
                           state["menu"]["state_version"], state["last_sequence"], answers)
    assert result["status"] == "COMMITTED", result
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    saves = {e.actor_id for e in loaded.engine.events if e.event_type == "SAVE_ROLLED"
             and BREATH in (e.source_definition_id or "")}
    packets = [e for e in loaded.engine.events if e.event_type == "DAMAGE_COMMITTED"
               and (BREATH in (e.source_definition_id or "") or AUGMENT in (e.source_definition_id or ""))]
    assert saves == {RIGHT}
    assert packets and all(e.target_ids == (RIGHT,) for e in packets)
    for who in (LEFT, ALLY):
        actor = loaded.engine.state.actors[who]
        assert actor.current_hp == before["actors"][who]["current_hp"]
        assert actor.reaction_available == before["actors"][who]["reaction_available"]
    assert loaded.verify()["status"] == loaded.mechanical.replay()["status"] == "PASS"


@pytest.mark.parametrize("ask", [False, True], ids=["manual", "ask-me"])
def test_choking_smoke_choice_only_offers_hostiles_and_cold_replays(tmp_path, ask):
    ability = "TAL_ALCHEMY_CHOKING_SMOKE_PELLET"
    combat, table, mid = table_fight(tmp_path, [ability], ask=ask, ally_talents=[])
    result, option = _commit_area_action(table, mid, "Choking Smoke Pellet", {"x": 4, "y": 4})
    assert result["status"] == "REACTION_REQUIRED", result
    prompt = result["reaction"]
    assert prompt["context"]["reaction_source_id"] == "choice:needle.area_recipients"
    assert {o["id"] for o in prompt["choice"]["options"]} == {RIGHT}
    answers = [{**prompt["context"], "selection": "USE", "option_ids": [RIGHT]}]
    for _ in range(20):
        table = TabletopService(CombatService(ROOT, tmp_path), tmp_path)
        state = table.state(mid)
        result = table.act(mid, option["candidate_id"], state["menu"]["decision_id"],
                           state["menu"]["state_version"], state["last_sequence"], answers)
        if result["status"] == "COMMITTED":
            break
        assert result["status"] == "REACTION_REQUIRED", result
        answers.append({**result["reaction"]["context"], "selection": "DECLINE"})
    assert result["status"] == "COMMITTED", result
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    assert {e.actor_id for e in loaded.engine.events if e.event_type == "SAVE_ROLLED"
            and ability in (e.source_definition_id or "")} == {RIGHT}
    for who in (LEFT, ALLY):
        assert loaded.engine.state.actors[who].current_hp == 60
        assert not any("silenced" in key for key in loaded.engine.state.actors[who].conditions)
    assert loaded.verify()["status"] == loaded.mechanical.replay()["status"] == "PASS"


def test_flood_benefit_choice_does_not_widen_hostile_disadvantage_after_reload(tmp_path):
    from tests.worker2_support import OWNER, ALLY as FRIEND, FOE, fixture, candidate, settle, reload
    court, flood = "TAL_WATER_COURT_OF_THE_ENDLESS_TIDE", "TAL_WATER_FLOOD_THE_BATTLEFIELD"
    combat, table, mid = fixture(tmp_path, [court, flood], foe_position={"x": 4, "y": 3})
    settle(table, mid, candidate(combat, mid, "Court of the Endless Tide").candidate_id)
    settle(table, mid, candidate(combat, mid, "Flood the Battlefield").candidate_id,
           {"choice:needle.area_recipients": [FOE]})
    engine = reload(tmp_path, mid)
    def disadvantages(who):
        return [c for c in engine.state.actors[who].conditions.values()
                if flood in (c.source_definition_id or "")
                and "DISADVANTAGE" in (c.data.get("rule") or {}).get("check_mode", {}).values()]
    assert disadvantages(FOE), "the hostile disadvantage must still apply"
    assert not disadvantages(OWNER) and not disadvantages(FRIEND)


@pytest.mark.parametrize("shape", ["cone", "line"])
@pytest.mark.parametrize("placed", [False, True])
def test_inclusive_origin_shape_excludes_user_but_placed_shape_can_hit_them(shape, placed):
    user, ally, enemy = _Actor("user", "a", 3, 4), _Actor("ally", "a", 4, 4), _Actor("enemy", "b", 5, 4)
    effect = {"type": "damage", "flat": 4,
              "recipient_text": "Every creature in the area takes damage."}
    area = scoped_area({"shape": shape, "size_ft": 30, "placed": placed,
                        "include_self": True, "include_origin": True}, [effect])
    # A remotely placed shape starts west of the caster and projects east.
    center = type(user.position)(x=2, y=4) if placed else enemy.position
    if placed:
        user.position = type(user.position)(x=1, y=4)
        # A Large caster's footprint overlaps the remotely placed origin.
        user.occupied_cells = ((1, 4), (2, 4))
    targets = _area_targets(_Engine([user, ally, enemy]), user, center, area)
    assert (user in targets) is placed
    assert harmful_area_subject_allowed(user, user, area, effect) is placed


@pytest.mark.parametrize("qualifier,scope", [("hostile", "enemies_in_area"),
                                               ("allied", "allies_in_area"),
                                               ("willing", "allies_in_area")])
def test_qualified_choice_and_unrelated_benefit_preserve_harm_scope(qualifier, scope):
    effect = {"type": "damage", "flat": 4, "applies_to": scope,
              "recipient_text": f"Each {qualifier} creature of your choice takes damage."}
    area = scoped_area({"shape": "sphere", "size_ft": 15}, [effect],
                       "Creatures of your choice gain temporary hit points. Each hostile creature takes damage.")
    user, ally, enemy = _Actor("user", "a", 3, 4), _Actor("ally", "a", 3, 5), _Actor("enemy", "b", 4, 4)
    expected = [enemy] if scope == "enemies_in_area" else [ally]
    assert [a for a in (ally, enemy) if harmful_area_subject_allowed(user, a, area, effect)] == expected


@pytest.mark.parametrize("sibling_kind", ["damage", "damage-target", "damage-default", "save", "benefit"],
                         ids=["direct-packet", "target-packet", "default-packet", "identical-save-children", "beneficial-sibling"])
def test_chosen_harm_does_not_widen_sibling_hostile_damage_after_table_reload(tmp_path, monkeypatch, sibling_kind):
    from combat.gate2_runtime_models import ActionDefinition, EconomyKind
    from tests.test_lock_choices import install
    source, name = "test:selfhit-mixed-payload", "Chosen burst with hostile pressure"
    def compile_area(info):
        if info["actor_id"] != LEFT:
            return []
        actions = [ActionDefinition(source_definition_id=source, display_name=name, owner_id=LEFT,
            economy=EconomyKind.ACTION, resolution_kind="TYPED", target_kind="SELF", radius_ft=15,
            parameters={"typed": {"numbers": {**info["numbers"], "save_dc": 99},
                "area": {"shape": "sphere", "size_ft": 15, "centered_on_self": True},
                "effects": [{"type": "rider_choose_area_recipients"},
                    {"type": "save", "ability": "dex", "dc": 99, "applies_to": "creatures_in_area",
                     "recipient_text": "Creatures of your choice make a Dexterity saving throw.",
                     "on_fail": [{"type": "damage", "flat": 5, "damage_types": ["force"]}]},
                    {"type": "damage", "flat": 3, "damage_types": ["force"], "applies_to": "enemies_in_area",
                     "recipient_text": "Each hostile creature takes damage."}]}})]
        # Seal the synthetic action just as _action_definition seals real rows.
        typed = actions[0].parameters["typed"]
        if sibling_kind == "damage-target":
            typed["effects"][-1]["applies_to"] = "target"
        elif sibling_kind == "damage-default":
            del typed["effects"][-1]["applies_to"]
        elif sibling_kind == "save":
            typed["effects"][-1] = {"type": "save", "ability": "dex", "dc": 99,
                "applies_to": "enemies_in_area", "recipient_text": "Each hostile creature makes a Dexterity saving throw.",
                "on_fail": [{"type": "damage", "flat": 5, "damage_types": ["force"]}]}
        elif sibling_kind == "benefit":
            typed["effects"][1]["applies_to"] = "enemies_in_area"
            typed["effects"][1]["recipient_text"] = "Each hostile creature of your choice makes a Dexterity saving throw."
            typed["effects"][-1] = {"type": "temp_hp", "flat": 3, "applies_to": "creatures_in_area",
                                   "evidence": "Creatures of your choice gain 3 temporary hit points."}
        typed["area"] = scoped_area(typed["area"], typed["effects"], typed=typed)
        return actions
    install(monkeypatch, "compile_actions", compile_area)
    combat, table, mid = table_fight(tmp_path, [], ally_talents=[])
    result, option = _commit_area_action(table, mid, name, None)
    assert result["status"] == "REACTION_REQUIRED", result
    prompt = result["reaction"]
    assert {row["id"] for row in prompt["choice"]["options"]} == {LEFT, ALLY, RIGHT}
    answers = [{**prompt["context"], "selection": "USE", "option_ids": [ALLY, RIGHT]}]
    for _ in range(20):
        table = TabletopService(CombatService(ROOT, tmp_path), tmp_path)
        state = table.state(mid)
        result = table.act(mid, option["candidate_id"], state["menu"]["decision_id"],
                           state["menu"]["state_version"], state["last_sequence"], answers)
        if result["status"] == "COMMITTED":
            break
        assert result["status"] == "REACTION_REQUIRED", result
        answers.append({**result["reaction"]["context"], "selection": "DECLINE"})
    assert result["status"] == "COMMITTED", result
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    assert loaded.engine.state.actors[ALLY].current_hp == (60 if sibling_kind == "benefit" else 55)
    assert loaded.engine.state.actors[RIGHT].current_hp == (50 if sibling_kind == "save" else
                                                         55 if sibling_kind == "benefit" else 52)
    assert loaded.engine.state.actors[LEFT].current_hp == 60
    area = loaded.engine.action_catalog[source].parameters["typed"]["area"]
    assert "harmful_recipient_override" not in area
    if sibling_kind == "benefit":
        assert loaded.engine.state.actors[ALLY].temporary_hp == loaded.engine.state.actors[RIGHT].temporary_hp == 3
    else:
        assert set(area["harmful_payload_scopes"].values()) == {"all", "hostile"}
    assert loaded.verify()["status"] == loaded.mechanical.replay()["status"] == "PASS"


@pytest.mark.parametrize("shape", ["sphere", "cone", "line"])
@pytest.mark.parametrize("evidence", [True, False], ids=["own-evidence", "printed-fallback"])
@pytest.mark.parametrize("packet", ["explicit-hostile", "generic-force", "generic-fire"])
def test_evidence_only_mixed_packets_survive_table_reload(tmp_path, monkeypatch, shape, evidence, packet):
    """Inclusive allies/self stay reachable; emitted breath never hits its user."""
    from combat.gate2_runtime_models import ActionDefinition, EconomyKind
    from tests.test_lock_choices import install
    source, name = "test:selfhit-evidence-packets", "Mixed fire and force burst"
    inclusive = "Each creature in the area takes 5 fire damage."
    damage_type = "fire" if packet == "generic-fire" else "force"
    hostile = (f"Each hostile creature in the area takes 3 {damage_type} damage."
               if packet == "explicit-hostile" else
               f"Creatures in the area take 3 {damage_type} damage.")

    def compile_area(info):
        if info["actor_id"] != LEFT:
            return []
        effects = [{"type": "damage", "flat": 5, "damage_types": ["fire"],
                    "applies_to": "creatures_in_area"},
                   {"type": "damage", "flat": 3, "damage_types": [damage_type],
                    "applies_to": "creatures_in_area" if packet == "explicit-hostile" else "enemies_in_area"}]
        if evidence:
            for row, sentence in zip(effects, (inclusive, hostile)):
                row["evidence"] = sentence
        area = {"shape": shape, "size_ft": 30, "include_origin": True}
        if shape == "sphere":
            area["centered_on_self"] = True
        typed = {"numbers": info["numbers"], "effects": effects}
        typed["area"] = scoped_area(area, effects, inclusive + " " + hostile, typed=typed)
        return [ActionDefinition(source_definition_id=source, display_name=name, owner_id=LEFT,
            economy=EconomyKind.ACTION, resolution_kind="TYPED",
            target_kind="SELF" if shape == "sphere" else "CELL", range_ft=30, radius_ft=30,
            parameters={"typed": typed})]

    install(monkeypatch, "compile_actions", compile_area)
    combat, table, mid = table_fight(tmp_path, [], ally_talents=[],
        starts={"team1": [[3, 4], [4, 4]], "team2": [[5, 4]]})
    result, _ = _commit_area_action(table, mid, name, None if shape == "sphere" else {"x": 5, "y": 4})
    assert result["status"] == "COMMITTED", result
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    assert loaded.engine.state.actors[ALLY].current_hp == 55
    assert loaded.engine.state.actors[RIGHT].current_hp == 52
    assert loaded.engine.state.actors[LEFT].current_hp == (55 if shape == "sphere" else 60)
    area = loaded.engine.action_catalog[source].parameters["typed"]["area"]
    assert set(area["harmful_payload_scopes"].values()) == {"all", "hostile"}
    assert "harmful_recipient_override" not in area
    from combat.area_recipients import harmful_effect_scope
    effects = loaded.engine.action_catalog[source].parameters["typed"]["effects"]
    assert [harmful_effect_scope(area, row) for row in effects] == ["all", "hostile"]
    packets = [event for event in loaded.engine.events if event.event_type == "DAMAGE_COMMITTED"
               and event.source_definition_id == source]
    assert packets
    if shape != "sphere":
        assert not any(LEFT in event.target_ids for event in packets)
    assert loaded.verify()["status"] == loaded.mechanical.replay()["status"] == "PASS"


def test_ambiguous_printed_sibling_clauses_do_not_widen_opaque_packet():
    effect = {"type": "damage", "flat": 7}
    area = scoped_area({"shape": "sphere", "size_ft": 15}, [effect],
        "Each creature takes 5 fire damage. Each hostile creature takes 3 force damage.")
    user, ally, enemy = _Actor("user", "a", 3, 4), _Actor("ally", "a", 3, 5), _Actor("enemy", "b", 4, 4)
    assert not harmful_area_subject_allowed(user, ally, area, effect)
    assert harmful_area_subject_allowed(user, enemy, area, effect)


@pytest.mark.parametrize("recipient_token", ["enemies_in_area", "target", None],
                         ids=["enemy-token", "target-token", "default-token"])
def test_mixed_area_hostile_packet_does_not_offer_unaffected_ally_reaction(recipient_token):
    from combat.typed_reactions import _incoming_is_adverse
    user, ally, enemy = _Actor("user", "a", 3, 4), _Actor("ally", "a", 3, 5), _Actor("enemy", "b", 4, 4)
    harm = {"type": "damage", "flat": 3, "recipient_text": "Each hostile creature takes damage."}
    if recipient_token is not None:
        harm["applies_to"] = recipient_token
    # The inclusive sibling is a benefit: the ally is in the area, but no
    # harmful payload reaches it. Reaction eligibility must use that scope.
    effects = [harm, {"type": "temp_hp", "flat": 3, "applies_to": "creatures_in_area"}]
    # Retain mixed-area policy as compiled beside an inclusive/chosen payload.
    inclusive = {"type": "damage", "flat": 5,
                 "recipient_text": "Creatures of your choice take damage."}
    area = scoped_area({"shape": "sphere", "size_ft": 15}, [harm, inclusive])
    assert set(area["harmful_payload_scopes"].values()) == {"all", "hostile"}
    typed = {"area": area, "effects": effects}
    assert not _incoming_is_adverse(user, ally, typed)
    assert not harmful_area_subject_allowed(user, ally, area, harm)
    assert _incoming_is_adverse(user, enemy, typed)


@pytest.mark.parametrize("manual", [True, False], ids=["manual-ask-me", "automatic"])
def test_chosen_save_ally_counter_survives_table_commit_and_cold_reload(tmp_path, monkeypatch, manual):
    from combat.gate2_runtime_models import ActionDefinition, EconomyKind
    from combat.tabletop import ButtonStore
    from tests.test_lock_choices import install
    from tests.test_sol140r2_area_reactions import COUNTER, counter_bundle
    from tests.test_tabletop_hunt6 import PROJECTS

    source, name = "test:selfhit-chosen-save-counter", "Chosen burst with hostile pressure"
    def compile_area(info):
        if info["actor_id"] != LEFT:
            return []
        effects = [{"type": "rider_choose_area_recipients"},
            {"type": "save", "ability": "dex", "applies_to": "enemies_in_area",
             "recipient_text": "Creatures of your choice make a Dexterity saving throw.",
             "on_fail": [{"type": "damage", "flat": 5, "damage_types": ["force"],
                          "applies_to": "enemies_in_area"}]},
            {"type": "save", "ability": "dex", "applies_to": "enemies_in_area",
             "recipient_text": "Each hostile creature makes a Dexterity saving throw.",
             "on_fail": [{"type": "damage", "flat": 3, "damage_types": ["force"],
                          "applies_to": "enemies_in_area"}]}]
        typed = {"numbers": {**info["numbers"], "save_dc": 99}, "effects": effects,
                 "area": {"shape": "sphere", "size_ft": 15, "centered_on_self": True}}
        typed["area"] = scoped_area(typed["area"], effects, typed=typed)
        assert set(typed["area"]["harmful_payload_scopes"].values()) == {"all", "hostile"}
        assert "harmful_recipient_override" not in typed["area"]
        return [ActionDefinition(source_definition_id=source, display_name=name, owner_id=LEFT,
            economy=EconomyKind.ACTION, resolution_kind="TYPED", target_kind="SELF", radius_ft=15,
            parameters={"typed": typed})]

    install(monkeypatch, "compile_actions", compile_area)
    counter_bundle(monkeypatch, {ALLY})
    ButtonStore(tmp_path / "tabletop_buttons").save_reactions(PROJECTS["ally"], {"mode": "ask"}, {COUNTER})
    combat, table, mid = table_fight(tmp_path, [], ally_talents=[],
        control_modes={LEFT: "MANUAL", ALLY: "MANUAL" if manual else "LOCAL_AUTO", RIGHT: "MANUAL"})
    before = combat._load_session(mid).engine.state.model_dump(mode="json")
    result, option = _commit_area_action(table, mid, name, None)
    assert result["status"] == "REACTION_REQUIRED", result
    prompt = result["reaction"]
    assert prompt["context"]["reaction_source_id"] == "choice:needle.area_recipients"
    assert {row["id"] for row in prompt["choice"]["options"]} == {LEFT, ALLY, RIGHT}
    answers = [{**prompt["context"], "selection": "USE", "option_ids": [ALLY, RIGHT]}]
    counter_prompts = []
    for _ in range(20):
        table = TabletopService(CombatService(ROOT, tmp_path), tmp_path)
        state = table.state(mid)
        result = table.act(mid, option["candidate_id"], state["menu"]["decision_id"],
                           state["menu"]["state_version"], state["last_sequence"], answers)
        if result["status"] == "COMMITTED":
            break
        assert result["status"] == "REACTION_REQUIRED", result
        prompt = result["reaction"]
        assert prompt["context"]["reactor_id"] == ALLY
        assert COUNTER in prompt["context"]["reaction_source_id"]
        counter_prompts.append(prompt)
        assert name in prompt["trigger"] and "Ally" in prompt["trigger"]
        assert "Counter the incoming technique" in str(prompt)
        answers.append({**prompt["context"], "selection": "USE"})
    assert result["status"] == "COMMITTED", result
    assert len(counter_prompts) == int(manual)
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    counters = [e for e in loaded.engine.events if e.event_type == "REACTION_RESOLVED"
                and e.source_definition_id == COUNTER]
    assert [e.actor_id for e in counters] == ([ALLY] if manual else [])
    ally = loaded.engine.state.actors[ALLY]
    if not manual:
        # Automatic seats deliberately avoid damaging retaliation against allies.
        # That separate policy must not hide whether the incoming save is harmful.
        from combat.typed_reactions import _incoming_is_adverse
        assert _incoming_is_adverse(loaded.engine.state.actors[LEFT], ally,
                                   loaded.engine.action_catalog[source].parameters["typed"])
    assert ally.reaction_available is (not manual)
    assert ally.resources["resource:core.qi"] == before["actors"][ALLY]["resources"]["resource:core.qi"] - int(manual)
    assert ally.current_hp == 55
    assert loaded.engine.state.actors[RIGHT].current_hp == 52
    assert loaded.engine.state.actors[LEFT].current_hp == 60 - int(manual)  # manual ally's counter
    assert loaded.verify()["status"] == loaded.mechanical.replay()["status"] == "PASS"


def test_runtime_recipient_selector_accepts_plain_gm_notes(monkeypatch):
    """Runtime notes are supported; compiled catalog effects remain dictionaries."""
    from types import SimpleNamespace
    from combat import zones
    from combat.ext import needle
    from combat.ext.rider_outcomes import choose_area_recipients
    user, ally, enemy = _Actor("user", "a", 3, 4), _Actor("ally", "a", 3, 5), _Actor("enemy", "b", 4, 4)
    for actor in (user, ally, enemy):
        actor.display_name = actor.entity_id.title()
    seen = []
    def ask(_engine, _intent, _checkpoint, _actor, _source, ids, **kwargs):
        seen.extend(ids)
        return ids
    monkeypatch.setattr(needle, "ask", ask)
    monkeypatch.setattr(needle, "checkpoint_id", lambda *args: "test:runtime-note")
    monkeypatch.setattr(zones, "uses_default_shape", lambda *args: False)
    selector = {"type": "rider_choose_area_recipients"}
    harm = {"type": "damage", "flat": 3, "applies_to": "enemies_in_area"}
    ctx = SimpleNamespace(actor=user, engine=SimpleNamespace(), intent=None,
        source="test:runtime-note", numbers={"pb": 4}, targets=[user, ally, enemy], target=None,
        action=SimpleNamespace(display_name="Selective practice burst", costs=[]),
        typed={"area": {"shape": "sphere", "size_ft": 15, "recipients": "all",
                        "harmful_recipients": "hostile", "include_self": True},
               "effects": [selector, harm, "A separate note for the game master."]})
    choose_area_recipients(ctx, selector)
    assert seen == [enemy.entity_id]
    assert ctx.targets == [enemy] and ctx.typed["_area_recipients_preselected"]


@pytest.mark.parametrize("shape", ["sphere", "cone", "line"])
def test_inclusive_area_keeps_self_damage_and_explains_own_effect_after_reload(tmp_path, monkeypatch, shape):
    from combat.gate2_runtime_models import ActionDefinition, EconomyKind
    from tests.test_lock_choices import install
    source, name = "test:selfhit-inclusive-burst", "Inclusive practice burst"
    def compile_area(info):
        if info["actor_id"] != LEFT:
            return []
        return [ActionDefinition(source_definition_id=source, display_name=name, owner_id=LEFT,
            economy=EconomyKind.ACTION, resolution_kind="TYPED", target_kind="SELF" if shape == "sphere" else "CELL",
            range_ft=30, radius_ft=15,
            parameters={"typed": {"numbers": info["numbers"],
                "area": {"shape": shape, "size_ft": 15, "centered_on_self": shape == "sphere"},
                "effects": [{"type": "save", "ability": "dex", "dc": 99,
                    "applies_to": "enemies_in_area", "recipient_text": "Each creature in the area makes a Dexterity saving throw.",
                    "on_fail": [{"type": "damage", "flat": 17, "damage_types": ["force"]}],
                    "on_success": [{"type": "half_damage"}]}]}})]
    install(monkeypatch, "compile_actions", compile_area)
    combat, table, mid = table_fight(tmp_path, [GUARD], ask=True, ally_talents=[], primary="Stamina",
                                   starts={"team1": [[3, 4], [4, 4]], "team2": [[5, 4]]})
    result, option = _commit_area_action(table, mid, name, None if shape == "sphere" else {"x": 5, "y": 4})
    answers, own_prompt = [], None
    for _ in range(24):
        if result["status"] == "COMMITTED":
            break
        assert result["status"] == "REACTION_REQUIRED", result
        prompt = result["reaction"]
        if prompt["context"]["reactor_id"] == LEFT and "stamina_guard" in prompt["context"]["reaction_source_id"]:
            own_prompt = prompt
            assert f"their own effect: {name}" in prompt["trigger"]
            assert "Left is about to take 17 damage" in prompt["trigger"]
            assert "Stamina Guard" in prompt["trigger"]
        answers.append({**prompt["context"], "selection": "DECLINE"})
        table = TabletopService(CombatService(ROOT, tmp_path), tmp_path)
        state = table.state(mid)
        result = table.act(mid, option["candidate_id"], state["menu"]["decision_id"],
                           state["menu"]["state_version"], state["last_sequence"], answers)
    assert result["status"] == "COMMITTED", result
    assert bool(own_prompt) is (shape == "sphere")
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    saves = {e.actor_id for e in loaded.engine.events if e.event_type == "SAVE_ROLLED"
             and e.source_definition_id == source}
    assert saves == ({LEFT, ALLY, RIGHT} if shape == "sphere" else {ALLY, RIGHT})
    assert (loaded.engine.state.actors[LEFT].current_hp < 60) is (shape == "sphere")
    assert loaded.verify()["status"] == loaded.mechanical.replay()["status"] == "PASS"
