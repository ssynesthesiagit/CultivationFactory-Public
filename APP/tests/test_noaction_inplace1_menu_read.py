"""NOACTIONINPLACE1: a free setting choice asks /act for its complete state in one response (menu_read)."""

import pytest
from pydantic import ValidationError

from app.models import TabletopActRequest, TabletopMenuRead


def test_menu_read_defaults_describe_a_plain_state_read():
    read = TabletopMenuRead()
    assert read.fog is False
    assert read.fog_view is None
    assert read.fog_actor_ids == []
    assert read.compact is False


def test_menu_read_carries_the_clients_state_read_arguments():
    read = TabletopMenuRead(fog=True, fog_view="own", fog_actor_ids=["a1", "a2"], compact=True)
    assert read.model_dump() == {"fog": True, "fog_view": "own", "fog_actor_ids": ["a1", "a2"], "compact": True}


def test_menu_read_rejects_unknown_fields():
    with pytest.raises(ValidationError):
        TabletopMenuRead(fog=True, verbose=True)


def test_act_request_accepts_menu_read_and_defaults_to_none():
    body = TabletopActRequest(candidate_id="c1", decision_id="d1", state_version=3, menu_read={"fog": True, "compact": True})
    assert body.menu_read.compact is True
    assert TabletopActRequest(candidate_id="c1", decision_id="d1", state_version=3).menu_read is None
