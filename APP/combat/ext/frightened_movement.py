"""Compatibility import for FIX33's shared Frightened path helper.

The native engine now owns canonical path filtering and per-step enforcement.
This module registers no candidate_allowed hook; old rider-route imports call
the same pure native helper rather than retaining a second implementation.
"""
from ..voluntary_movement import path_allowed
