"""Character tokens (owner 2026-09-27: "put a custom image in and have it cut a circle making a token, and also use the
model to create a token"). combat/portraits.py, TabletopService token methods."""

import base64
import json
import struct
import zlib
from pathlib import Path

import pytest

from combat import portraits as tokens
from combat.tabletop import TabletopError
from combat.tabletop_service import TabletopService

PID = "0badc0de-0000-4000-8000-00000000000a"


def _png(width: int, height: int) -> bytes:
    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
    rows = b"".join(b"\x00" + b"\x00\x00\x00\x00" * width for _ in range(height))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(rows)) + chunk(b"IEND", b""))


def _service(tmp_path: Path) -> TabletopService:
    service = TabletopService(None, tmp_path)

    class Combat:
        userdata_root = tmp_path

        def _factory_owner_sheet(self, project_id):
            return {"identity": {"species": "Human", "title": "Bone Monarch", "concept": "A forest-born cultivator"},
                    "spheres_and_talents": {"sphere_record_ids": ["tianxia.sphere.death", "tianxia.sphere.ash"]}}

    service.combat = Combat()
    return service


def test_a_cropped_png_is_kept_and_the_table_finds_it(tmp_path):
    service = _service(tmp_path)
    saved = service.save_token(PID, "data:image/png;base64," + base64.b64encode(_png(512, 512)).decode())
    assert saved["token_url"].startswith(f"/api/tabletop/characters/{PID}/token.png?v=")
    assert service.token_path(PID).read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
    found = service._tokens_for([f"actor:factory.{PID}", f"actor:factory.{PID}.summon.1", "actor:gate1.an"])
    assert list(found) == [f"actor:factory.{PID}"]
    service.delete_token(PID)
    assert service._tokens_for([f"actor:factory.{PID}"]) == {}


def test_only_a_sensible_png_is_accepted(tmp_path):
    service = _service(tmp_path)
    with pytest.raises(TabletopError):
        service.save_token(PID, base64.b64encode(b"GIF89a not a png at all").decode())
    with pytest.raises(TabletopError):
        service.save_token(PID, base64.b64encode(_png(16, 16)).decode())  # too small to be a token


def test_the_portrait_prompt_puts_the_owners_words_first_and_reads_the_spheres():
    prompt = tokens.portrait_prompt(_service(Path("."))
                                    .combat._factory_owner_sheet(PID), "young man, long black hair")
    assert prompt.index("young man, long black hair") < prompt.index("human xianxia cultivator")
    assert "pale bone ornaments" in prompt and "ash-grey embers" in prompt and "known as Bone Monarch" in prompt


def test_anima_uses_the_graph_of_the_accepted_trial():
    receipt = Path.home() / ".local/opt/anima-character-trial/receipts/01_reference_turbo.json"
    if not receipt.is_file():
        pytest.skip("Anima trial receipts are not on this machine")
    trial = json.loads(receipt.read_text())["payload"]["prompt"]
    ours = tokens._graph("a prompt", 7)
    assert {key: row["class_type"] for key, row in ours.items()} == {key: row["class_type"] for key, row in trial.items()}
    for node in ("1", "2", "3", "6", "8"):
        assert ours[node]["inputs"] == trial[node]["inputs"]
    assert {k: v for k, v in ours["7"]["inputs"].items() if k != "seed"} == {k: v for k, v in trial["7"]["inputs"].items() if k != "seed"}


def test_a_full_picture_is_kept_beside_the_token_and_anima_paints_it_taller(tmp_path):
    service = _service(tmp_path)
    saved = service.save_picture(PID, base64.b64encode(_png(768, 1152)).decode())
    assert saved["picture_url"].startswith(f"/api/tabletop/characters/{PID}/picture.png?v=")
    assert service.picture_path(PID).is_file()
    service.save_token(PID, base64.b64encode(_png(512, 512)).decode(), {"x": 0.5, "y": 0.31, "r": 0.19})
    assert service.buttons.get(PID)["token_circle"] == {"x": 0.5, "y": 0.31, "r": 0.19}  # the dialog reopens it there
    graph = tokens._graph("p", 1, *tokens.FRAMINGS["upper"][1:2], height=tokens.FRAMINGS["upper"][2])
    assert graph["6"]["inputs"]["width"] == 768 and graph["6"]["inputs"]["height"] == 1152
    assert "upper body" in tokens.portrait_prompt({"identity": {}}, None, "upper")
    service.delete_picture(PID)
    assert service._picture_store().url(PID) is None


def test_a_summoned_creature_gets_a_token_from_its_kinds_pool(tmp_path):
    from types import SimpleNamespace

    service = _service(tmp_path)
    for kind, count in (("corpse_servant", 3), ("wolf", 2)):
        (service.summon_token_root() / kind).mkdir(parents=True)
        for index in range(1, count + 1):
            (service.summon_token_root() / kind / f"{index}.png").write_bytes(_png(64, 64))
    actors = {f"s{n}": SimpleNamespace(entity_id=f"s{n}", summon={"group": "corpse_servant"}) for n in range(6)}
    actors["beast"] = SimpleNamespace(entity_id="beast", summon={"group": "beast0.wolf"})
    actors["hero"] = SimpleNamespace(entity_id="hero", summon=None)
    engine = SimpleNamespace(state=SimpleNamespace(actors=actors))
    service.combat._load_session = lambda match_id: SimpleNamespace(engine=engine)
    tokens_ = service._summon_tokens("m")
    assert set(tokens_) == {*(f"s{n}" for n in range(6)), "beast"}
    assert all(url.startswith("/api/tabletop/summon-tokens/corpse_servant/") for key, url in tokens_.items() if key != "beast")
    assert tokens_["beast"].startswith("/api/tabletop/summon-tokens/wolf/")
    assert len({tokens_[f"s{n}"] for n in range(6)}) > 1 and service._summon_tokens("m") == tokens_  # varied, and stable
    assert service.summon_token_path("wolf", "1.png").is_file()
    with pytest.raises(TabletopError):
        service.summon_token_path("../x", "1.png")


def test_conditions_are_described_from_the_rules_the_engine_applies():
    from combat.condition_text import all_conditions

    table = all_conditions()
    assert "Its attack rolls have Disadvantage" in table["prone"]["mechanics"]
    assert "It automatically fails Strength and Dexterity saving throws" in table["stunned"]["mechanics"]
    assert table["smothered"]["mechanics"] == ["It can't take Reactions"]
    assert table["burning"]["reading"] and not table["burning"]["automated"]
