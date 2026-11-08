"""Standalone candidate Tianxia content-pack validator.

CPK-1 status: CANDIDATE_NON_AUTHORITATIVE.
This package is intentionally isolated from all Factory runtime registries.
"""

from .validator import ValidationOptions, ValidationResult, validate_content_pack

__all__ = ["ValidationOptions", "ValidationResult", "validate_content_pack"]
__version__ = "0.1.0"
__candidate_status__ = "CANDIDATE_NON_AUTHORITATIVE"
