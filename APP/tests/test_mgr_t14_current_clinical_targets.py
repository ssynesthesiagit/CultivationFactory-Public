"""Current target-variant labels, with the original native service assertions.

Keep these five changed cases independently selectable as a whole public-CI
file; the rest of clinical_native is qualified by its existing whole-file job.
"""
from tests.test_mgr_t14_clinical_native import (
    final_native_mechanical_replay,
    test_blood_consent_and_exact_one_source,
    test_coagulate_native_temp_hp_bands,
    test_coagulate_native_stabilization,
)
