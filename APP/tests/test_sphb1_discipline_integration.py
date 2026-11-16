"""Both approved discipline selectors honor one persisted player choice."""
from combat.ext import defensive_disciplines as disciplines
from tests.test_auto1_paths_a import TEMPERED, _service_discipline
from tests.test_sph_foundations_r1 import fixture, act, reload, BLAST, ME


def test_setup_choice_is_seen_by_failed_save_selector_after_reload(tmp_path):
    engine, actor, row = _service_discipline(tmp_path, TEMPERED, "DEX", "SPHB1-SETUP")
    assert disciplines.chosen(engine, actor, TEMPERED) == "DEX"
    assert disciplines.discipline_abilities(engine, actor, row) == ["DEX"]
    assert actor.entity_id not in disciplines.discipline_owners(engine)
    assert not disciplines._can_choose(engine, actor, TEMPERED)


def test_failed_save_choice_disables_setup_selector_after_reload(tmp_path, monkeypatch):
    combat, table, mid = fixture(tmp_path, monkeypatch)
    cid = next(c["candidate_id"] for c in combat.decision(mid)["context"]["legal_candidates"]
               if c["display_name"] == BLAST and ME in c["target_ids"])
    result = act(combat, table, mid, cid)
    assert result["status"] == "REACTION_REQUIRED"
    prompt = result["reaction"]
    answer = {**prompt["context"], "selection": "USE", "option_ids": ["DEX"]}
    assert act(combat, table, mid, cid, [answer])["status"] == "COMMITTED"
    _, _, engine = reload(tmp_path, mid)
    actor = engine.state.actors[ME]
    assert disciplines._recorded(engine, actor, TEMPERED) == "DEX"
    assert not disciplines._can_choose(engine, actor, TEMPERED)
    row = next(r for r in engine.typed_reaction_rows[ME] if r["feature_id"] == TEMPERED)
    disciplines.apply_recorded_disciplines(engine)
    assert row["abilities"] == ["DEX"]
