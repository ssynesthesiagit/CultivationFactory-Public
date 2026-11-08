"""Dependency-free contract constants for lineage Manuals and Recorded Arts.

This module deliberately lives outside the ``character_creation`` package so
Stage 2 can import the event and outcome contract before that package's
initializer imports its execution service.
"""
from __future__ import annotations

from copy import deepcopy

MANUAL_PACK_ID = "tianxia.project.factory_constructed.manual"
RECORDED_ART_PACK_ID = "tianxia.project.factory_constructed.recorded_art"
MANUAL_PACK_VERSION = "1"
MANUAL_CHANNEL = "factory-constructed-lineage-manual"
RECORDED_ART_CHANNEL = "factory-constructed-recorded-art"
MANUAL_TRAINING_CHANNEL = "manual-training"
RECORDED_ART_CONSTRUCTION_KIND = "creation_recorded_art_acquisition"
MANUAL_ACCESS_MODE = "inherited_lineage_manual"
MANUAL_OUTCOME_SCHEMA = "TianxiaFoundry.ConstructedRecordedArtOutcome.v1"
MANUAL_OUTCOME = {
    "schema": MANUAL_OUTCOME_SCHEMA,
    "result": "learned",
    "mode": "automatic_construction",
    "dice_simulated": False,
    "counts_against_trained_choices": False,
    "slot_cost": 0,
}


def manual_outcome() -> dict[str, object]:
    """Return a fresh copy of the exact non-rolled art acquisition outcome."""
    return deepcopy(MANUAL_OUTCOME)


__all__ = [
    "MANUAL_ACCESS_MODE",
    "MANUAL_CHANNEL",
    "MANUAL_OUTCOME",
    "MANUAL_OUTCOME_SCHEMA",
    "MANUAL_PACK_ID",
    "MANUAL_PACK_VERSION",
    "MANUAL_TRAINING_CHANNEL",
    "RECORDED_ART_CHANNEL",
    "RECORDED_ART_CONSTRUCTION_KIND",
    "RECORDED_ART_PACK_ID",
    "manual_outcome",
]
