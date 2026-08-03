from __future__ import annotations

import base64
import binascii
import hashlib
import struct
import zlib
from pathlib import Path

from fastapi.testclient import TestClient

from app.api import create_app
from app.core import Settings
from combat.map_calibration import normalize_map_visual

ROOT = Path(__file__).resolve().parents[1]


def _png(width: int, height: int) -> bytes:
    def chunk(kind: bytes, payload: bytes) -> bytes:
        return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", binascii.crc32(kind + payload) & 0xFFFFFFFF)

    # RGB, no interlace, one filter byte per row.
    row = b"\x00" + b"\x44\x66\x88" * width
    raw = row * height
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw))
        + chunk(b"IEND", b"")
    )


def _client(tmp_path: Path) -> TestClient:
    return TestClient(create_app(Settings.from_env(ROOT, tmp_path / "UserData")))


def _headers(client: TestClient) -> dict[str, str]:
    return {"x-foundry-token": client.get("/api/session").json()["token"]}


def _payload(data: bytes, mode: str) -> dict[str, str]:
    return {
        "original_filename": "gridless-map.png",
        "media_type": "image/png",
        "data_base64": base64.b64encode(data).decode("ascii"),
        "calibration_mode": mode,
    }


def test_exact_calibration_normalizes_only_when_bound_to_asset_and_grid() -> None:
    digest = "a" * 64
    row = {
        "asset_id": "battlemap:test:exact",
        "public_url": "/map.png",
        "sha256": digest,
        "source": "match_snapshot",
        "width_px": 2000,
        "height_px": 1400,
        "calibration": {
            "schema": "TianxiaBattleMapCalibration.v2",
            "authority": "PRESENTATION_ONLY",
            "grid_width_squares": 20,
            "grid_height_squares": 14,
            "source_pixel_width": 2000,
            "source_pixel_height": 1400,
            "playable_rect_pixels": {"x": 0, "y": 0, "width": 2000, "height": 1400},
            "fit_mode": "EXACT_PLAYABLE_RECT",
            "position_x_percent": 50,
            "position_y_percent": 50,
            "asset_sha256": digest,
        },
    }
    projection, findings = normalize_map_visual(row, grid_width=20, grid_height=14)
    assert projection is not None
    assert projection.calibration.status == "EXACT_REGISTERED"
    assert projection.calibration.exact_landmark_alignment is True
    assert findings == ()

    mismatched = {**row, "calibration": {**row["calibration"], "grid_width_squares": 19}}
    projection, findings = normalize_map_visual(mismatched, grid_width=20, grid_height=14)
    assert projection is not None
    assert projection.calibration.status == "INVALID"
    assert findings[0]["code"] == "map_calibration_invalid"

    wrong_ratio = {
        **row,
        "calibration": {
            **row["calibration"],
            "source_pixel_width": 1400,
            "source_pixel_height": 1400,
            "playable_rect_pixels": {"x": 0, "y": 0, "width": 1400, "height": 1400},
        },
        "width_px": 1400,
        "height_px": 1400,
    }
    projection, findings = normalize_map_visual(wrong_ratio, grid_width=20, grid_height=14)
    assert projection is not None
    assert projection.calibration.status == "INVALID"
    assert "aspect ratio" in projection.calibration.message


def test_legacy_and_decorative_calibrations_never_claim_exact_alignment() -> None:
    row = {
        "asset_id": "battlemap:test:legacy",
        "public_url": "/legacy.png",
        "sha256": "b" * 64,
        "width_px": 1254,
        "height_px": 1254,
        "calibration": {
            "schema": "TianxiaBattleMapCalibration.v1",
            "fit_mode": "cover",
            "position_x_percent": 50,
            "position_y_percent": 50,
            "scale_percent": 100,
        },
    }
    projection, findings = normalize_map_visual(row, grid_width=20, grid_height=14)
    assert projection is not None
    assert projection.calibration.status == "LEGACY_DECORATIVE"
    assert projection.calibration.exact_landmark_alignment is False
    assert findings[0]["code"] == "map_calibration_legacy_decorative"


def test_exact_upload_is_ratio_validated_and_snapshotted_for_live_and_history(tmp_path: Path) -> None:
    client = _client(tmp_path)
    exact_png = _png(200, 140)
    square_png = _png(140, 140)
    with client:
        headers = _headers(client)
        rejected = client.post(
            "/api/combat/setup-visuals/background",
            headers=headers,
            json=_payload(square_png, "EXACT_PLAYABLE_RECT"),
        )
        assert rejected.status_code == 422
        assert "aspect ratio" in rejected.json()["error"]["message"]

        accepted = client.post(
            "/api/combat/setup-visuals/background",
            headers=headers,
            json=_payload(exact_png, "EXACT_PLAYABLE_RECT"),
        )
        assert accepted.status_code == 200, accepted.text
        selected = next(row for row in accepted.json()["maps"] if row["source"] == "owner_upload")
        assert selected["width_px"] == 200
        assert selected["height_px"] == 140
        assert selected["calibration"]["fit_mode"] == "EXACT_PLAYABLE_RECT"
        assert selected["calibration"]["asset_sha256"] == hashlib.sha256(exact_png).hexdigest()

        catalog = client.get("/api/combat/catalog").json()
        modes = {
            row["runtime_entity_id"]: "LOCAL_AUTO"
            for row in catalog["projections"]
            if row.get("primary_combatant")
        }
        created = client.post(
            "/api/combat/matches",
            headers=headers,
            json={
                "encounter_id": catalog["encounters"][0]["stable_id"],
                "display_name": "E3 exact map test",
                "match_seed": "R6-6-8-E3-EXACT-MAP",
                "control_modes": modes,
                "maximum_rounds": 20,
            },
        )
        assert created.status_code == 200, created.text
        match_id = created.json()["match_id"]
        live = client.get(f"/api/combat/matches/{match_id}/presentation").json()
        history = client.get(f"/api/combat/matches/{match_id}/presentation?boundary=0").json()
        for projection in (live, history):
            calibration = projection["map_visual"]["calibration"]
            assert calibration["status"] == "EXACT_REGISTERED"
            assert calibration["exact_landmark_alignment"] is True
            assert calibration["playable_rect_pixels"] == {"x": 0, "y": 0, "width": 200, "height": 140}
        assert live["map_visual"] == history["map_visual"]


def test_browser_uses_exact_grid_tracks_and_occupied_cell_mask() -> None:
    script = (ROOT / "static/app.js").read_text(encoding="utf-8")
    css = (ROOT / "static/styles.css").read_text(encoding="utf-8")
    html = (ROOT / "static/index.html").read_text(encoding="utf-8")

    assert "function appendCombatTokenGroup" in script
    assert 'group.style.gridColumn = `${anchorX + 1} / span ${width}`' in script
    assert 'group.style.gridRow = `${anchorY + 1} / span ${height}`' in script
    assert "footprint.occupied_cells" in script
    assert 'segment.style.gridColumn = String(relativeX + 1)' in script
    assert 'segment.style.gridRow = String(relativeY + 1)' in script
    assert "width !== 1" not in script
    assert ".combat-token-layer" in css
    assert ".combat-footprint-mask" in css
    assert ".combat-token.multicell-token" in css
    assert "width: 155%" not in css
    assert "width: 170%" not in css

    assert "function appendCombatMapLayer" in script
    assert 'calibration?.status === "EXACT_REGISTERED"' in script
    assert 'image.style.left = `${-rect.x / rect.width * 100}%`' in script
    assert 'image.style.width = `${sourceWidth / rect.width * 100}%`' in script
    assert 'id="combatCalibrationStatus"' in html
    assert 'value="EXACT_PLAYABLE_RECT"' in html
