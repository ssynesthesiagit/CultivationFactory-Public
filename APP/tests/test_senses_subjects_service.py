"""P1 subjects retain source identity and share existing perception decisions."""
from types import SimpleNamespace

from combat import senses
from pathlib import Path

from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from tests.test_effect_durations import _fight
from tests.test_flightsight import table_yard

APP = Path(__file__).resolve().parents[1]


def test_subject_assessment_keeps_effect_separate_from_visible_caster(monkeypatch):
    engine, observer, caster = _fight("INVISIBLE")
    caster_subject = senses.creature_subject(caster)
    hidden_effect = SimpleNamespace(perception_subject=None)
    effect_subject = senses.effect_subject("effect:private", hidden_effect, host=caster)
    monkeypatch.setattr(senses, "perceives", lambda _e, _v, target, **kw: target is caster)
    monkeypatch.setattr(senses, "pinpoints", lambda *_: False)

    caster_result = senses.assess(engine, observer, caster_subject)
    effect_result = senses.assess(engine, observer, effect_subject)
    assert caster_result["sight"] is True
    assert effect_result["sight"] is False
    assert effect_result["subject"] == "effect:private"
    assert effect_result["rejection"] == "You cannot perceive that from here."


def test_object_subject_preserves_source_and_uses_existing_object_adapter(monkeypatch):
    obj = SimpleNamespace(object_id="object:mark-1")
    seen = []
    monkeypatch.setattr(senses, "perceives_object", lambda _e, _v, source: seen.append(source) or True)
    result = senses.assess(object(), object(), senses.object_subject(obj), purpose="visual_sight")
    assert seen == [obj]
    assert result["allowed"] is True
    assert result["subject"] == obj.object_id


def test_table_projection_agrees_after_commit_and_cold_reload(tmp_path):
    _, table, match_id, (viewer_id, target_id) = table_yard(tmp_path, (15, 0))
    before = table.state(match_id, fog=True)
    viewer_before = before["fog_perception"][viewer_id]
    menu = before["menu"]
    assert table.act(match_id, menu["end_turn"], menu["decision_id"], menu["state_version"],
                     before["last_sequence"])["status"] == "COMMITTED"

    cold = TabletopService(CombatService(APP, tmp_path), tmp_path)
    after = cold.state(match_id, fog=True)["fog_perception"][viewer_id]
    assert (target_id in viewer_before["creatures"]) == (target_id in after["creatures"])
    assert viewer_before["cells"] == after["cells"]
    assert viewer_before["objects"] == after["objects"]


def test_creature_assessment_keeps_sight_and_location_independent(monkeypatch):
    engine, observer, target = _fight("INVISIBLE")
    monkeypatch.setattr(senses, "perceives", lambda *_a, **_kw: False)
    monkeypatch.setattr(senses, "pinpoints", lambda *_a: True)
    result = senses.assess(engine, observer, senses.creature_subject(target), purpose="known_location")
    assert result["sight"] is False
    assert result["location"] is True
    assert result["allowed"] is True
    assert result["rejection"] is None
