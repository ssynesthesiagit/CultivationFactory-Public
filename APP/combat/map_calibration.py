from __future__ import annotations

from typing import Any, Literal

from pydantic import Field, model_validator

from .models import StrictModel

MAP_CALIBRATION_SCHEMA = "TianxiaBattleMapCalibration.v2"
MAP_VISUAL_SCHEMA = "TianxiaBattleMapVisualProjection.v1"


class PixelRect(StrictModel):
    x: int = Field(ge=0)
    y: int = Field(ge=0)
    width: int = Field(ge=1)
    height: int = Field(ge=1)


class BattleMapCalibrationProjection(StrictModel):
    schema_name: Literal[MAP_CALIBRATION_SCHEMA] = Field(default=MAP_CALIBRATION_SCHEMA, alias="schema")
    authority: Literal["PRESENTATION_ONLY"] = "PRESENTATION_ONLY"
    status: Literal[
        "EXACT_REGISTERED",
        "DECORATIVE_CONTAIN",
        "DECORATIVE_COVER",
        "LEGACY_DECORATIVE",
        "MISSING",
        "INVALID",
    ]
    fit_mode: Literal["EXACT_PLAYABLE_RECT", "CONTAIN_DECORATIVE", "COVER_DECORATIVE"] | None = None
    grid_width_squares: int = Field(ge=1)
    grid_height_squares: int = Field(ge=1)
    source_pixel_width: int | None = Field(default=None, ge=1)
    source_pixel_height: int | None = Field(default=None, ge=1)
    playable_rect_pixels: PixelRect | None = None
    position_x_percent: float = Field(default=50, ge=0, le=100)
    position_y_percent: float = Field(default=50, ge=0, le=100)
    asset_sha256: str | None = None
    source_schema: str | None = None
    exact_landmark_alignment: bool = False
    message: str

    @model_validator(mode="after")
    def validate_exact_status(self) -> "BattleMapCalibrationProjection":
        if self.status == "EXACT_REGISTERED":
            if self.fit_mode != "EXACT_PLAYABLE_RECT" or self.playable_rect_pixels is None:
                raise ValueError("exact calibration requires an exact playable rectangle")
            if not self.exact_landmark_alignment:
                raise ValueError("exact calibration must assert exact landmark alignment")
        elif self.exact_landmark_alignment:
            raise ValueError("decorative or invalid calibration cannot assert exact landmark alignment")
        return self


class MapVisualProjection(StrictModel):
    schema_name: Literal[MAP_VISUAL_SCHEMA] = Field(default=MAP_VISUAL_SCHEMA, alias="schema")
    asset_id: str
    public_url: str
    sha256: str | None = None
    source: str | None = None
    original_filename: str | None = None
    width_px: int | None = Field(default=None, ge=1)
    height_px: int | None = Field(default=None, ge=1)
    calibration: BattleMapCalibrationProjection
    mechanical_authority: Literal[False] = False


def _integer(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        result = int(value)
    except (TypeError, ValueError):
        return None
    return result if result > 0 else None


def _float(value: Any, default: float) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    return result


def _invalid(
    *,
    grid_width: int,
    grid_height: int,
    source_width: int | None,
    source_height: int | None,
    asset_sha256: str | None,
    source_schema: str | None,
    message: str,
) -> BattleMapCalibrationProjection:
    return BattleMapCalibrationProjection(
        status="INVALID",
        grid_width_squares=grid_width,
        grid_height_squares=grid_height,
        source_pixel_width=source_width,
        source_pixel_height=source_height,
        asset_sha256=asset_sha256,
        source_schema=source_schema,
        message=message,
    )


def normalize_map_visual(
    row: dict[str, Any],
    *,
    grid_width: int,
    grid_height: int,
) -> tuple[MapVisualProjection | None, tuple[dict[str, str], ...]]:
    """Normalize snapshot metadata without granting it mechanical authority.

    Exact registration means only that the declared image playable rectangle maps
    one-to-one onto the authoritative grid viewport. Terrain and cover continue to
    come exclusively from the typed battlefield definition.
    """

    public_url = row.get("public_url")
    asset_id = row.get("asset_id")
    if not isinstance(public_url, str) or not public_url or not isinstance(asset_id, str) or not asset_id:
        return None, ({
            "code": "map_visual_invalid",
            "severity": "ERROR",
            "message": "The match map visual is missing an exact asset identity or public URL. Battlefield geometry remains authoritative.",
        },)

    source_width = _integer(row.get("width_px"))
    source_height = _integer(row.get("height_px"))
    asset_sha256 = row.get("sha256") if isinstance(row.get("sha256"), str) else None
    raw = row.get("calibration")
    findings: list[dict[str, str]] = []

    if not isinstance(raw, dict):
        calibration = BattleMapCalibrationProjection(
            status="MISSING",
            grid_width_squares=grid_width,
            grid_height_squares=grid_height,
            source_pixel_width=source_width,
            source_pixel_height=source_height,
            asset_sha256=asset_sha256,
            message="No typed map calibration is present. The image is decorative; the application grid and typed geometry remain authoritative.",
        )
        findings.append({
            "code": "map_calibration_missing",
            "severity": "WARNING",
            "message": calibration.message,
        })
    elif raw.get("schema") == MAP_CALIBRATION_SCHEMA:
        source_schema = MAP_CALIBRATION_SCHEMA
        declared_grid_width = _integer(raw.get("grid_width_squares"))
        declared_grid_height = _integer(raw.get("grid_height_squares"))
        declared_source_width = _integer(raw.get("source_pixel_width"))
        declared_source_height = _integer(raw.get("source_pixel_height"))
        fit_mode = raw.get("fit_mode")
        declared_sha = raw.get("asset_sha256") if isinstance(raw.get("asset_sha256"), str) else None
        pos_x = _float(raw.get("position_x_percent"), 50)
        pos_y = _float(raw.get("position_y_percent"), 50)
        rect_raw = raw.get("playable_rect_pixels")
        rect: PixelRect | None = None
        try:
            if isinstance(rect_raw, dict):
                rect = PixelRect.model_validate(rect_raw)
        except ValueError:
            rect = None

        invalid_reason: str | None = None
        if declared_grid_width != grid_width or declared_grid_height != grid_height:
            invalid_reason = "The map calibration grid dimensions do not match the authoritative battlefield."
        elif not declared_source_width or not declared_source_height:
            invalid_reason = "The map calibration does not declare valid source pixel dimensions."
        elif source_width and source_width != declared_source_width:
            invalid_reason = "The map calibration source width does not match the snapshotted image metadata."
        elif source_height and source_height != declared_source_height:
            invalid_reason = "The map calibration source height does not match the snapshotted image metadata."
        elif declared_sha != asset_sha256 or not declared_sha:
            invalid_reason = "The map calibration is not bound to the snapshotted image SHA-256."
        elif not (0 <= pos_x <= 100 and 0 <= pos_y <= 100):
            invalid_reason = "The decorative map position is outside the accepted percentage range."
        elif fit_mode not in {"EXACT_PLAYABLE_RECT", "CONTAIN_DECORATIVE", "COVER_DECORATIVE"}:
            invalid_reason = "The map calibration fit mode is unsupported."
        elif rect is None:
            invalid_reason = "The map calibration playable rectangle is missing or invalid."
        elif rect.x + rect.width > declared_source_width or rect.y + rect.height > declared_source_height:
            invalid_reason = "The map playable rectangle extends outside the source image."
        elif fit_mode == "EXACT_PLAYABLE_RECT":
            # Exact registration cannot stretch a mismatched playable rectangle.
            lhs = rect.width * grid_height
            rhs = rect.height * grid_width
            tolerance = max(lhs, rhs) * 0.001
            if abs(lhs - rhs) > tolerance:
                invalid_reason = "The exact playable rectangle aspect ratio does not match the authoritative battlefield grid."

        if invalid_reason:
            calibration = _invalid(
                grid_width=grid_width,
                grid_height=grid_height,
                source_width=declared_source_width or source_width,
                source_height=declared_source_height or source_height,
                asset_sha256=asset_sha256,
                source_schema=source_schema,
                message=f"{invalid_reason} Geometry remains authoritative; visual landmark alignment is not accepted.",
            )
            findings.append({"code": "map_calibration_invalid", "severity": "ERROR", "message": calibration.message})
        else:
            assert rect is not None
            if fit_mode == "EXACT_PLAYABLE_RECT":
                status = "EXACT_REGISTERED"
                message = "Exact gridless-map registration: the declared playable rectangle is mapped directly to the authoritative battlefield grid."
                exact = True
            elif fit_mode == "CONTAIN_DECORATIVE":
                status = "DECORATIVE_CONTAIN"
                message = "Decorative contained map: blank margins may remain and visible landmarks are not asserted to match typed geometry."
                exact = False
            else:
                status = "DECORATIVE_COVER"
                message = "Decorative covered map: image cropping may occur and visible landmarks are not asserted to match typed geometry."
                exact = False
            calibration = BattleMapCalibrationProjection(
                status=status,
                fit_mode=fit_mode,
                grid_width_squares=grid_width,
                grid_height_squares=grid_height,
                source_pixel_width=declared_source_width,
                source_pixel_height=declared_source_height,
                playable_rect_pixels=rect,
                position_x_percent=pos_x,
                position_y_percent=pos_y,
                asset_sha256=asset_sha256,
                source_schema=source_schema,
                exact_landmark_alignment=exact,
                message=message,
            )
            if not exact:
                findings.append({
                    "code": "map_calibration_decorative",
                    "severity": "INFO",
                    "message": message,
                })
    elif raw.get("schema") == "TianxiaBattleMapCalibration.v1":
        fit = raw.get("fit_mode")
        if fit not in {"cover", "contain", "stretch"}:
            calibration = _invalid(
                grid_width=grid_width,
                grid_height=grid_height,
                source_width=source_width,
                source_height=source_height,
                asset_sha256=asset_sha256,
                source_schema="TianxiaBattleMapCalibration.v1",
                message="The legacy map calibration fit mode is invalid. Geometry remains authoritative.",
            )
            findings.append({"code": "map_calibration_invalid", "severity": "ERROR", "message": calibration.message})
        else:
            # Stretch is retained only as a legacy decorative compatibility mode.
            normalized_fit = "CONTAIN_DECORATIVE" if fit == "contain" else "COVER_DECORATIVE"
            calibration = BattleMapCalibrationProjection(
                status="LEGACY_DECORATIVE",
                fit_mode=normalized_fit,
                grid_width_squares=grid_width,
                grid_height_squares=grid_height,
                source_pixel_width=source_width,
                source_pixel_height=source_height,
                playable_rect_pixels=(
                    PixelRect(x=0, y=0, width=source_width, height=source_height)
                    if source_width and source_height else None
                ),
                position_x_percent=_float(raw.get("position_x_percent"), 50),
                position_y_percent=_float(raw.get("position_y_percent"), 50),
                asset_sha256=asset_sha256,
                source_schema="TianxiaBattleMapCalibration.v1",
                exact_landmark_alignment=False,
                message="Legacy decorative calibration retained for compatibility. Cropping or distortion may occur; typed geometry remains authoritative.",
            )
            findings.append({
                "code": "map_calibration_legacy_decorative",
                "severity": "INFO",
                "message": calibration.message,
            })
    else:
        calibration = _invalid(
            grid_width=grid_width,
            grid_height=grid_height,
            source_width=source_width,
            source_height=source_height,
            asset_sha256=asset_sha256,
            source_schema=str(raw.get("schema") or "unknown"),
            message="The map calibration schema is unsupported. Geometry remains authoritative and visual alignment is not accepted.",
        )
        findings.append({"code": "map_calibration_invalid", "severity": "ERROR", "message": calibration.message})

    projection = MapVisualProjection(
        asset_id=asset_id,
        public_url=public_url,
        sha256=asset_sha256,
        source=row.get("source") if isinstance(row.get("source"), str) else None,
        original_filename=row.get("original_filename") if isinstance(row.get("original_filename"), str) else None,
        width_px=source_width,
        height_px=source_height,
        calibration=calibration,
    )
    return projection, tuple(findings)
