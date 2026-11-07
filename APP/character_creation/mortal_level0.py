"""Provider-free mortal completion validation shared by the creator route."""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Mapping

from character_builder.service import CharacterBuilderService
from character_creation.creative_controller.factory_validator import validate_mortal_level0_completion
from character_creation.path_attainment import mortal_level0_path_attainment
from creation_training_authority import validate_mortal_level0_training


PHB_SOURCE_ID = "PHB"
PHB_SOURCE_SHA256 = "f2bb2eeba55a4b8b8630e02fbcb35d21ac80d2efb7ad4a9e91642522f82d7fe7"
PHB_LEVEL0_LOCATOR = "PHB v0.7 lines 324-345"
ABILITY_NAMES = ("STR", "DEX", "CON", "INT", "WIS", "CHA")


class MortalLevel0ValidationError(ValueError):
    """Structured rejection from the connected mortal completion seam."""

    def __init__(self, code: str, **details: Any) -> None:
        self.code = code
        self.details = details
        super().__init__(code if not details else f"{code}: {details}")


def _require(condition: bool, code: str, **details: Any) -> None:
    if not condition:
        raise MortalLevel0ValidationError(code, **details)


def source_ref(*, locator: str = PHB_LEVEL0_LOCATOR) -> dict[str, str]:
    return {"source_id": PHB_SOURCE_ID, "source_hash": PHB_SOURCE_SHA256, "locator": locator}


def validate_mortal_level0_choices(
    *,
    name: str,
    base_abilities: Mapping[str, int],
    selected_paths: list[str] | tuple[str, ...] = (),
    training_choices: list[Any] | tuple[Any, ...] = (),
) -> dict[str, Any]:
    """Run the existing point-buy validator plus the mortal-only dispatches."""

    _require(isinstance(name, str) and name.strip() == name and bool(name), "LEVEL0_NAME_INVALID")
    _require(tuple(base_abilities) == ABILITY_NAMES, "LEVEL0_ABILITIES_MISMATCH")
    try:
        point_buy = CharacterBuilderService.validate_point_buy(dict(base_abilities))
        completion = validate_mortal_level0_completion(target_cl=0, selected_paths=selected_paths)
        training = validate_mortal_level0_training(target_cl=0, training_choices=training_choices)
    except (ValueError, TypeError, KeyError) as exc:
        code = getattr(exc, "code", None) or str(exc) or "LEVEL0_CREATOR_VALIDATION_FAILED"
        raise MortalLevel0ValidationError(str(code)) from exc
    _require(point_buy.get("completion") == "owner_complete", "LEVEL0_POINT_BUY_INCOMPLETE")
    return {
        "schema": "TianxiaFoundry.MortalLevel0Completion.v1",
        "route": completion,
        "training": training,
        "name": name,
        "base_abilities": dict(base_abilities),
        "point_buy": deepcopy(point_buy),
        "path_attainment": mortal_level0_path_attainment(),
        "source": source_ref(),
        "selected_paths": [],
        "training_choices": [],
    }
