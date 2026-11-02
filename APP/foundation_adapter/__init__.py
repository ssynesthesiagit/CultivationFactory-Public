"""Foundation 46/113 handoff adapter.

This package converts the immutable Foundation Factory-App handoff into native
Foundry catalog record blueprints.  It deliberately does not install packs or
modify project replacement policy; those responsibilities remain in the
Content Pack and project-lock services.
"""

from .handoff import (
    EXPECTED_HANDOFF_SHA256,
    FoundationHandoff,
    FoundationHandoffError,
    load_foundation_handoff,
)
from .service import (
    FOUNDATION_PACK_ID,
    FOUNDATION_PACK_VERSION,
    FoundationPackPlan,
    bind_native_records,
    build_foundation_replacement_map,
    build_native_pack_bytes,
    build_foundation_pack_plan,
    load_pinned_core_foundation_authorities,
    validate_native_record_projection,
    write_deterministic_foundation_pack,
)

__all__ = [
    "EXPECTED_HANDOFF_SHA256",
    "FOUNDATION_PACK_ID",
    "FOUNDATION_PACK_VERSION",
    "FoundationHandoff",
    "FoundationHandoffError",
    "FoundationPackPlan",
    "bind_native_records",
    "build_foundation_replacement_map",
    "build_native_pack_bytes",
    "build_foundation_pack_plan",
    "load_foundation_handoff",
    "load_pinned_core_foundation_authorities",
    "validate_native_record_projection",
    "write_deterministic_foundation_pack",
]
