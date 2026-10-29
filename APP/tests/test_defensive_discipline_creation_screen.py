"""DEFDISC1 creation screen (F6R finding 1): the creation screen offers the Path's Defensive Discipline pick. A client
that answers must answer every pick its Paths offer; a client that sends no answers at all (quick creation, scripts)
still creates the character, whose pick the table offers later. A pick is never asked in a fight."""
from fastapi.testclient import TestClient

from app.api import create_app
from tests.catalog_clone_support import _clone_catalog_db

BODY = "tianxia.path.body_refining"
TEMPERED = "tianxia.path.body_refining.feature.tempered_response"


def _client(catalog_environment, tmp_path):
    settings, db = _clone_catalog_db(catalog_environment, tmp_path / "creation screen")
    client = TestClient(create_app(settings))
    client.__enter__()
    token = client.get("/api/session").json()["token"]
    return client, {"x-foundry-token": token}


def _body(feature_choices=None, **overrides):
    body = {"working_name": "Pick Test", "concept": "A steady fighter who relies on firm footing.",
            "target_cl": 15, "power_band": "heroic", "creation_mode": "detailed",
            "ability_scores": {"STR": 15, "CON": 14, "WIS": 12}, "selections": {"path_choice": [BODY]}}
    if feature_choices is not None:
        body["feature_choices"] = feature_choices
    return {**body, **overrides}


def test_the_creation_screen_offers_the_tempered_response_pick_with_its_printed_options(catalog_environment, tmp_path):
    client, _ = _client(catalog_environment, tmp_path)
    try:
        data = client.get("/api/character-builder/feature-build-choices", params={"path_ids": BODY}).json()
        feature = next(row for row in data["features"] if row["feature_id"] == TEMPERED)
        assert feature["name"] == "Tempered Response"
        assert [option["id"] for option in feature["options"]] == ["str", "dex", "con"]
        assert feature["prompt"]
    finally:
        client.__exit__(None, None, None)


def test_the_creation_screen_rejects_a_path_the_rules_do_not_know(catalog_environment, tmp_path):
    client, _ = _client(catalog_environment, tmp_path)
    try:
        response = client.get("/api/character-builder/feature-build-choices", params={"path_ids": "tianxia.path.nope"})
        assert response.status_code == 422
    finally:
        client.__exit__(None, None, None)


def test_answering_a_pick_that_is_not_the_offered_one_is_refused_in_plain_words(catalog_environment, tmp_path):
    # The request field is optional, but a client that answers must answer every pick its Paths offer: sending the Qi
    # Cultivation pick for a Body Refiner is a half answer, and the refusal names the missing pick.
    client, headers = _client(catalog_environment, tmp_path)
    try:
        response = client.post("/api/character-builder/projects", headers=headers,
                               json=_body({"tianxia.path.qi_cultivation.feature.cultivated_response": "dex"}))
        assert response.status_code == 409, response.text
        assert response.json()["error"]["code"] == "CHARACTER_FEATURE_CHOICE_REQUIRED", response.text
        assert response.json()["error"]["message"] == "Choose your Defensive Discipline for Tempered Response before creating the character.", response.text
    finally:
        client.__exit__(None, None, None)


def test_creating_a_body_refiner_with_the_pick_records_it_on_the_sheet(catalog_environment, tmp_path):
    client, headers = _client(catalog_environment, tmp_path)
    try:
        response = client.post("/api/character-builder/projects", headers=headers, json=_body({TEMPERED: "dex"}))
        assert response.status_code == 200, response.text
        # The recorded pick is the one the owner chose, not just an accepted request.
        assert TEMPERED in response.text and '"dex"' in response.text, response.text
    finally:
        client.__exit__(None, None, None)


def test_a_client_that_sends_no_pick_creates_the_character_and_the_table_offers_it_later(catalog_environment, tmp_path):
    # F12 finding 1: the field is optional, so a caller that never sends it (Quick mode, scripts, other tests) must not
    # be refused. The character keeps the compiled weakest-save row and the table's pick panel records the choice.
    client, headers = _client(catalog_environment, tmp_path)
    try:
        response = client.post("/api/character-builder/projects", headers=headers, json=_body())
        assert response.status_code == 200, response.text
        # Nothing was recorded: the character is created with the pick unchosen, which the creation-pick and
        # cold-reload tests cover on the sheet and on the compiled row.
    finally:
        client.__exit__(None, None, None)


def test_quick_creation_without_a_pick_also_creates_the_character(catalog_environment, tmp_path):
    # A hidden detailed-mode picker must not block Quick mode, even if an older client sends its stale answer.
    from pathlib import Path
    script = (Path(__file__).resolve().parents[1] / "static" / "app.js").read_text()
    assert "feature_choices: detailed ? collectFeaturePicks() : null" in script
    client, headers = _client(catalog_environment, tmp_path)
    try:
        response = client.post("/api/character-builder/projects", headers=headers,
                               json=_body({TEMPERED: "dex"}, creation_mode="quick", selections={}))
        assert response.status_code == 200, response.text
        assert TEMPERED not in response.text
    finally:
        client.__exit__(None, None, None)
