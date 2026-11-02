"""Public synthetic behavior parity for the record query boundary, including reload."""
import copy
import json
from pathlib import Path

from authority_records import RecordMap, recording
from combat import factory_compiler as compiler
from combat.gate2_runtime_models import ActionIntent
from combat.gate4_persistence import Gate4Persistence
from tests.test_typed_structure import AUTHORITY

ROOT = Path(__file__).resolve().parents[1]


class PlainAuthority:
    """The pre-boundary operations: plain dict lookup, no query wrappers."""
    def __init__(self, data, digest):
        self.data, self.digest = data, digest

    def records(self):
        return self.data["mechanics"]

    def resources(self):
        return self.data.get("resources") or {}

    def aggregate(self, section, default=None):
        return self.data.get(section, default)


def sheet():
    return {
        "identity": {"name": "Synthetic cultivator", "cultivation_level": 10,
                     "proficiency_bonus": 4, "key_ability": "CON"},
        "ability_scores_and_statistics": {
            "abilities": [{"ability": a, "score": 14, "modifier": 2}
                          for a in ("STR", "DEX", "CON", "INT", "WIS", "CHA")],
            "armor_class": {"base_value": 14}, "hit_points": {"maximum": 60},
            "speed": {"walking_ft": 30}, "primary_resource": {"name": "Qi", "maximum": 30},
            "technique_save_dc": 16, "technique_attack_bonus": 8},
        "spheres_and_talents": {"sphere_record_ids": ["tianxia.sphere.water"],
                               "learned_talent_record_ids": ["LASH", "WHIP", "EDGE"]},
    }


def test_plain_and_record_queries_preserve_complete_bundles_choices_events_and_reload(tmp_path, monkeypatch):
    data = copy.deepcopy(AUTHORITY)
    data["resources"] = {"charge": {"name": "Charge", "kind": "pool", "start": 1, "max": 2}}
    actor_ids = ("actor:factory.synthetic_left", "actor:factory.synthetic_right")
    docs = [sheet(), sheet()]
    expected = None
    dependencies = set()
    for facade in (PlainAuthority, compiler.Authority):
        with monkeypatch.context() as patch, recording(lambda rid, aspect: dependencies.add((rid, aspect))):
            patch.setattr(compiler, "Authority", facade)
            texts = {"LASH": "Synthetic Water Lash", "WHIP": "Synthetic Water Whip"}
            patch.setattr(compiler, "_RULES_TEXT_CACHE", texts if facade is PlainAuthority else RecordMap(texts, "rules"), raising=False)
            bundles = [compiler.compile_character(doc, actor_id=aid, typed_authority=data)
                       for doc, aid in zip(docs, actor_ids)]
        if expected is None:
            expected = bundles
        else:
            # Includes every action/variant/cost/limit, prompt metadata, passive,
            # provenance and hashes; no field or event category is filtered.
            assert bundles == expected
    assert any("+ Water Whip" in row["display_name"] for row in expected[0]["action_catalog"])
    assert {("LASH", "*"), ("WHIP", "*"), ("EDGE", "*"), ("@resources", "*"),
            ("@document", "provenance")} <= dependencies

    def play(root, bundles):
        persistence = Gate4Persistence(ROOT, root)
        session = persistence.create_match(
            match_seed="RECORD-IMPACT-PARITY", maximum_rounds=2, typed_bundles=tuple(bundles),
            roster_setup={"primary_actor_ids": list(actor_ids),
                          "team_by_actor": {actor_ids[0]: "team:a", actor_ids[1]: "team:b"},
                          "starting_positions": {actor_ids[0]: {"x": 3, "y": 6}, actor_ids[1]: {"x": 4, "y": 6}}})
        snapshots = []
        for step in range(6):
            engine = session.engine
            candidates = engine.legal_candidates()
            snapshots.append({"choices": [c.model_dump(mode="json") for c in candidates],
                              "state": engine.state.model_dump(mode="json"),
                              "events": [e.model_dump(mode="json") for e in engine.events]})
            if not candidates or engine.state.terminal_result:
                break
            chosen = next((c for c in candidates if c.display_name == "Water Lash"), None)
            chosen = chosen or next(c for c in candidates if c.kind.value == "END_TURN")
            session.submit_intent(ActionIntent(
                intent_id=f"parity:{step}", decision_id=chosen.decision_id,
                candidate_id=chosen.candidate_id, state_version=chosen.state_version,
                actor_id=chosen.actor_id, target_ids=chosen.target_ids, destination=chosen.destination),
                primary_decision_record=None, reaction_provider=None)
            session = Gate4Persistence(ROOT, root).load_match(session.match_id)
            assert session.verify()["status"] == "PASS"
        assert any(e["event_type"] == "ATTACK_ROLLED" for e in snapshots[-1]["events"])
        return snapshots

    assert play(tmp_path / "plain", expected) == play(tmp_path / "records", bundles)
