"""DEFDISC1 creation screen (F6R finding 1): the creation screen offers the Path's Defensive Discipline pick, and the
server refuses to create a Body Refiner or Qi Cultivator who has not chosen it. A pick is never asked in a fight."""
from fastapi.testclient import TestClient

from app.api import create_app
from tests.test_r6_6_7_character_builder_intake_catalog import _clone_catalog_db

BODY = "tianxia.path.body_refining"
TEMPERED = "tianxia.path.body_refining.feature.tempered_response"


def _client(catalog_environment, tmp_path):
    settings, db = _clone_catalog_db(catalog_environment, tmp_path / "creation screen")
    client = TestClient(create_app(settings))
    client.__enter__()
    token = client.get("/api/session").json()["token"]
    return client, {"x-foundry-token": token}


def _body(feature_choices=None):
    return {"working_name": "Pick Test", "concept": "A steady fighter who relies on firm footing.",
            "target_cl": 15, "power_band": "heroic", "creation_mode": "detailed",
            "ability_scores": {"STR": 15, "CON": 14, "WIS": 12}, "selections": {"path_choice": [BODY]},
            "feature_choices": feature_choices or {}}


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


def test_creating_a_body_refiner_without_a_discipline_pick_is_refused(catalog_environment, tmp_path):
    client, headers = _client(catalog_environment, tmp_path)
    try:
        response = client.post("/api/character-builder/projects", headers=headers, json=_body())
        assert response.status_code == 409, response.text
        assert response.json()["error"]["code"] == "TABLETOP_LEVEL_NOT_LEGAL", response.text
    finally:
        client.__exit__(None, None, None)


def test_creating_a_body_refiner_with_the_pick_records_it_on_the_sheet(catalog_environment, tmp_path):
    client, headers = _client(catalog_environment, tmp_path)
    try:
        response = client.post("/api/character-builder/projects", headers=headers, json=_body({TEMPERED: "dex"}))
        assert response.status_code == 200, response.text
    finally:
        client.__exit__(None, None, None)
