"""Focused native reruns for the shared combat/travel Body-speed extraction.

Each regression drives the original service/table assertions unchanged, without
rerunning unrelated native cases. The source command must quote the real Body
Speed and still deliver its full chosen route and effect receipts.
"""
from tests import test_living_quicksilver_native as native
from tests import test_living_quicksilver_review_f6 as review


def test_perfected_air_body_move_and_mirror_native_replay(tmp_path,monkeypatch):
    native.test_perfected_body_flight_mirror_object_attack_and_native_replay(tmp_path,monkeypatch)


def test_body_move_into_real_destroying_qi_and_pattern_recording(tmp_path,monkeypatch):
    native.test_native_body_destroying_hostile_qi_activation_still_permits_record_pattern(tmp_path,monkeypatch)


def test_body_move_visits_the_actual_intermediate_hazard(tmp_path,monkeypatch):
    review.test_body_walk_visits_intermediate_hazard_and_stops_when_destroyed(tmp_path,monkeypatch)
