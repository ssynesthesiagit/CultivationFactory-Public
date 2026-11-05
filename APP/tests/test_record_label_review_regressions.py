"""Public fixtures for legacy record identity and renamed Dark plug-in queries."""
from types import SimpleNamespace

import pytest

from combat import senses, stealth, zones
from combat.ext import dark_riders, tabik_dark
from factory_authoring import printed_references
from tests import hunt36_support as support
from tests.lighting_darkness_support import darkness_rules

DARK = "DARK_BASE_DARKNESS"
HIDE = "TAL_DARK_HIDE_IN_DARKNESS"
PURE = "TAL_DARK_PURE_DARKNESS"


@pytest.fixture
def printed_headings(monkeypatch):
    # Immutable source headings, not editable labels. Public CI omits source prose.
    headings = {"Darkness": [DARK], "Hide in Darkness": [HIDE], "Pure Darkness": [PURE]}
    texts = {rid: f"### {heading}" for heading, ids in headings.items() for rid in ids}
    monkeypatch.setattr(printed_references, "source_headings", lambda: (texts, headings))


@pytest.mark.parametrize("pure", [False, True])
def test_legacy_zone_and_hide_action_keep_rules_after_table_commit_and_reload(
        tmp_path, monkeypatch, darkness_rules, printed_headings, pure):
    original_compile = support.compile_character
    original_zone = zones.prospective_zone

    def old_bundle(*args, **kwargs):
        bundle = original_compile(*args, **kwargs)
        bundle.setdefault("senses", {})["rows"] = [
            {"feature_id": "test:vision", "sense": "darkvision", "range_ft": 60, "when": "always"},
            {"feature_id": "test:smell", "sense": "scent", "range_ft": 30, "when": "always"}]
        if bundle["actor_id"] == support.LEFT:
            bundle["senses"]["meld_start"] = HIDE
            for action in bundle["action_catalog"]:
                if action["parameters"].get("stealth") == "hide":
                    params = action["parameters"]
                    params.pop("hide_area_id", None)
                    params["hide_inside"] = "Darkness"
                    for effect in params["typed"]["effects"]:
                        if effect["type"] == "hide":
                            effect.update(inside="Darkness", bonus=40)
        return bundle

    def old_zone(*args, **kwargs):
        # Model the older writer at genesis, not a disposable engine mutation:
        # the real ZONE_CREATED event, table store and cold replay carry this shape.
        zone = original_zone(*args, **kwargs)
        zone.trigger_profile.pop("source_profile", None)
        zone.trigger_profile.pop("talent_ids", None)
        return zone

    monkeypatch.setattr(support, "compile_character", old_bundle)
    monkeypatch.setattr(zones, "prospective_zone", old_zone)
    combat, table, mid = support.fight(tmp_path, [DARK, HIDE, *([PURE] if pure else [])])
    support.turn(combat, table, mid)
    if pure:
        support.act(combat, table, mid, "Shape Darkness: Pure Darkness")
    engine = combat._load_session(mid).engine
    cast = next(c for c in engine.legal_candidates()
                if c.destination and (c.destination.x, c.destination.y) == (3, 6)
                and engine.action_catalog[c.source_definition_id].display_name == "Darkness")
    support.send(combat, table, mid, cast.candidate_id)
    support.act(combat, table, mid, "end")
    support.turn(combat, table, mid)
    engine = support.reload(combat, mid)
    me, foe = (engine.state.actors[aid] for aid in (support.LEFT, support.RIGHT))
    zone = next(z for z in zones.typed_zones(engine) if z.owner_id == support.LEFT)
    assert "source_profile" not in zone.trigger_profile and "talent_ids" not in zone.trigger_profile
    assert senses.pure_zone(zone) is pure
    assert senses.reach(engine, me, "darkvision", foe) == (5 if pure else 60)
    assert senses.reach(engine, me, "scent", foe) == (15 if pure else 30)
    assert stealth.in_own_area(engine, me, "Darkness")
    if not pure:
        assert senses.pierces(engine, zone, foe, me)
        assert stealth.sees(engine, foe, me), "Hide must override actual visibility, not ordinary concealment"
        hide = next(c for c in engine.legal_candidates()
                    if engine.action_catalog.get(c.source_definition_id)
                    and engine.action_catalog[c.source_definition_id].parameters.get("stealth") == "hide")
        support.send(combat, table, mid, hide.candidate_id)
        loaded = support.reload(combat, mid)
        hidden = loaded.state.actors[support.LEFT]
        assert stealth.hidden(hidden) is not None
        assert hidden.conditions[stealth.hidden(hidden)].data["inside"] == "Darkness"


@pytest.mark.parametrize("ids,labels,expected", [
    (["TAL_DARK_SHADOW_SLICK", dark_riders.TENEBROUS, "TAL_DARK_FEARFUL_DARKNESS",
      "TAL_DARK_BLACK_LUNG"], ["Renamed darkness talent"], True),
    (["UNRELATED_TALENT"], ["Shadow Slick", "Tenebrous Legerdemain", "Fearful Darkness", "Black Lung"], False),
    ([], ["Shadow Slick", "Tenebrous Legerdemain", "Fearful Darkness", "Black Lung"], False),
])
def test_dark_hooks_use_sealed_talent_ids_not_renamed_or_duplicate_labels(monkeypatch, ids, labels, expected):
    zone = SimpleNamespace(trigger_profile={"talent_ids": ids, "talents": labels},
                           source_definition_id="action:area", owner_id="owner", affected_cells=((1, 1),))
    actor = SimpleNamespace(entity_id="owner", saving_throws={"DEX": 3, "STR": 1}, conditions={})
    foe = SimpleNamespace(entity_id="foe")
    condition = SimpleNamespace(source_definition_id="action:area")
    engine = SimpleNamespace(state=SimpleNamespace(actors={"foe": foe}),
                             _footprint_intersects=lambda creature, cells: True)
    monkeypatch.setattr(zones, "typed_zones", lambda _: [zone])
    assert (dark_riders._from_talent(engine, condition, "TAL_DARK_BLACK_LUNG") is zone) is expected
    assert dark_riders.slick_escape(engine, actor, [SimpleNamespace(condition_id=dark_riders.GRAPPLED)]) == (
        "ADVANTAGE" if expected else None)
    action = SimpleNamespace(parameters={"dark_legerdemain": True})
    candidate = SimpleNamespace(target_ids=("foe",))
    assert dark_riders.legerdemain_target(engine, actor, candidate, action) is (None if expected else False)
    assert tabik_dark._zones_with(engine, "TAL_DARK_FEARFUL_DARKNESS") == ([zone] if expected else [])


def test_fearful_darkness_ends_outside_renamed_area(monkeypatch):
    zone = SimpleNamespace(trigger_profile={"talent_ids": ["TAL_DARK_FEARFUL_DARKNESS"],
                                           "talents": ["Renamed fear"]}, source_definition_id="action:area")
    frightened = SimpleNamespace(condition_id=tabik_dark.FRIGHTENED, source_definition_id="action:area",
                                 source_actor_id="caster", data={"fearful_darkness": True})
    actor = SimpleNamespace(entity_id="victim", conditions={"fear": frightened})
    events = []
    engine = SimpleNamespace(state=SimpleNamespace(zones={"area": zone}),
                             _append_event=lambda *args, **kwargs: events.append((args, kwargs)))
    monkeypatch.setattr(zones, "typed_zones", lambda _: [zone])
    monkeypatch.setattr(zones, "_inside", lambda *_: False)
    tabik_dark.dark_turn_end(engine, actor)
    assert actor.conditions == {}
    assert len(events) == 1 and events[0][0][0] == "CONDITION_REMOVED"


def test_zone_identity_prefers_sealed_sources_and_rejects_ambiguous_legacy_headings(printed_headings):
    from combat.zone_identity import source_id
    profile = {"name": "Darkness", "source_profile": {"mechanic_id": "OTHER"}}
    assert source_id(SimpleNamespace(trigger_profile=profile)) == "OTHER"
    profile.pop("source_profile")
    assert source_id(SimpleNamespace(trigger_profile=profile)) == DARK
    printed_references.source_headings()[1]["Darkness"].append("OTHER")
    assert source_id(SimpleNamespace(trigger_profile=profile)) is None


def test_unprinted_legacy_zone_name_cannot_grant_hide_permission(monkeypatch, printed_headings):
    actor = SimpleNamespace(entity_id="owner")
    zone = SimpleNamespace(owner_id="owner", trigger_profile={"name": "Arbitrary display label"})
    monkeypatch.setattr(zones, "typed_zones", lambda _: [zone])
    monkeypatch.setattr(zones, "_inside", lambda *_: True)
    monkeypatch.setattr(senses, "meld_active", lambda *_: True)
    assert not stealth.in_own_area(SimpleNamespace(), actor, "Arbitrary display label")
    # Explicit caller-authored IDs remain valid without being in the printed catalog.
    zone.trigger_profile["source_profile"] = {"mechanic_id": "SYNTHETIC_AREA"}
    assert stealth.in_own_area(SimpleNamespace(), actor, "SYNTHETIC_AREA")


def test_unprinted_talent_label_cannot_impersonate_a_sealed_id(printed_headings):
    from combat.zone_identity import has_talent
    zone = SimpleNamespace(trigger_profile={"talents": [PURE]})
    assert not has_talent(zone, PURE)
    zone.trigger_profile["talents"] = ["Pure Darkness"]
    assert has_talent(zone, PURE)
