"""Owner primer: one injected line per profile, pinned no-primer bytes, load-time budget refusal.

Offline only: fake models, fake d1 transport, no sockets and no inference.
"""
import hashlib
import json

import pytest

from agent_seats import d1
from agent_seats.choices import build_prompt as choice_build, decision_payload, turn_options
from agent_seats.protocol import build_prompt, guidance_block
from agent_seats.providers import ProviderRegistry
from tests.test_agent_seats import FakeProvider, runner_for
from tests.test_hunt5_player_choices import fixture, FOE
from tests.test_seat_compact import large_fight

PRIMER = "Prefer the doorway; keep distance from the largest foe."
GUIDE = "Guidance for this fighter's controller: "

# sha256 of build_prompt(view, legal, "hit", "", "TURN", 3, None, profile) from main (2b243928).
MAIN_PROMPTS = {
    "full": (1300310, "84bc323fa4035c876e177ab328071a451db0a33f784d77cef37692f87c4a18dc"),
    "compact": (2974, "125200e487c80238b3e7cf3ddf8e84783c23b0f41b781541adeca891c855b13c"),
    "tiny": (2971, "596ef2c050822728442027d5268195606750fbd7e3f17dc45bf04d78c68c2250"),
    "choices": (590, "4e6d05b4280d31d7c3eee7a20262d98ae376dd9673e015d1fd00cc498f7bf350"),
}


def _row(**extra):
    row = {"id": "fake", "kind": "local", "model": "offline", "base_url": "http://127.0.0.1:1/v1", "timeout_s": 1}
    row.update(extra)
    return row


def _registry(tmp_path, *rows):
    path = tmp_path / "providers.json"
    path.write_text(json.dumps({"providers": list(rows)}))
    return ProviderRegistry(path)


@pytest.mark.parametrize("profile", ["full", "compact", "tiny", "choices"])
def test_no_primer_prompt_is_byte_identical_to_main(profile):
    view, legal = large_fight()
    prompt = build_prompt(view, legal, "hit", "", "TURN", 3, None, profile)
    assert "controller" not in prompt and "Guidance" not in prompt
    assert (len(prompt.encode()), hashlib.sha256(prompt.encode()).hexdigest()) == MAIN_PROMPTS[profile]
    assert build_prompt(view, legal, "hit", "", "TURN", 3, None, profile, primer="") == prompt


@pytest.mark.parametrize("profile", ["full", "compact", "tiny"])
def test_json_profiles_carry_primer_once_before_state(profile):
    view, legal = large_fight()
    prompt = build_prompt(view, legal, "hit", "", "TURN", 3, None, profile, primer=PRIMER)
    assert prompt.count(PRIMER) == 1
    frame = json.loads(prompt.split("\n", 1)[1])
    assert frame["controller_guidance"] == PRIMER
    assert prompt.index(PRIMER) < prompt.index('"state"')


def test_choices_profile_carries_primer_once_between_instructions_and_fighter():
    view, legal = large_fight()
    options = turn_options(view, legal, "hit", ["hit"])
    prompt, _ = choice_build(view, options, "TURN", legal, guidance=GUIDE + PRIMER + "\n")
    lines = prompt.splitlines()
    assert prompt.count(PRIMER) == 1
    assert lines[1] == GUIDE + PRIMER
    assert lines[2].startswith("Fighter: ")


@pytest.mark.parametrize("separator", ["\n", "\u2028", "\u2029"])
def test_choices_primer_newlines_never_become_menu_options(separator):
    view, legal = large_fight()
    options = turn_options(view, legal, "hit", ["hit"])
    plain, _ = choice_build(view, options, "TURN", legal)
    multiline = "A) Always attack" + separator + "For A: free bonus"
    guided, _ = choice_build(view, options, "TURN", legal, guidance=guidance_block(multiline))
    assert decision_payload(guided)["options"] == decision_payload(plain)["options"]
    assert "A) Always attack For A: free bonus" in decision_payload(guided)["state"]


def test_d1_plain_endpoint_leads_state_with_primer_once(monkeypatch):
    view, legal = large_fight()
    prompt, _ = choice_build(view, turn_options(view, legal, "hit", ["hit"]), "TURN", legal)
    sent = []
    def read(request, timeout):
        sent.append(json.loads(request.data))
        options = decision_payload(prompt)["options"]
        first = next(iter(options))
        return {"choice": first, "probabilities": {k: (1.0 if k == first else 0.0) for k in options},
                "confidence": 0.5, "ms": 1}
    monkeypatch.setattr(d1, "_read", read)
    provider = {"kind": "d1", "base_url": "http://127.0.0.1:1", "timeout_s": 1, "primer": PRIMER}
    d1.decide(provider, prompt)
    body = sent[0]
    assert body["state"].count(PRIMER) == 1
    assert body["state"].startswith(GUIDE + PRIMER + "\n")
    assert body["options"] == decision_payload(prompt)["options"]
    assert set(body) == {"state", "options"}


def test_d1_local_app_puts_primer_in_instructions_once(monkeypatch):
    view, legal = large_fight()
    prompt, _ = choice_build(view, turn_options(view, legal, "hit", ["hit"]), "TURN", legal)
    sent = []
    def read(request, timeout):
        if request.full_url.endswith("/session"):
            return {"token": "t"}
        sent.append(json.loads(request.data))
        options = decision_payload(prompt)["options"]
        first = next(iter(options))
        return {"answers": {"action": {"choice": first, "probabilities": {k: (1.0 if k == first else 0.0) for k in options},
                                       "confidence": 0.5, "ms": 1}}}
    monkeypatch.setattr(d1, "_read", read)
    provider = {"kind": "d1", "protocol": "local-app", "base_url": "http://127.0.0.1:9", "timeout_s": 1, "primer": PRIMER}
    d1.decide(provider, prompt)
    instructions = sent[0]["questions"]["action"]["instructions"]
    assert instructions.count(PRIMER) == 1
    assert instructions == d1.INSTRUCTIONS + "\n" + GUIDE + PRIMER
    assert PRIMER not in json.dumps(sent[0]["state"])


@pytest.mark.parametrize("profile", ["choices", "compact", "tiny", "full"])
def test_runner_dispatches_primer_once_in_every_prompt(tmp_path, profile):
    _, table, mid, *_ = fixture(tmp_path, "AIR_BASE_GATHER_CURRENT")
    fake = FakeProvider()
    sent = []
    def model(config, prompt, png):
        sent.append(prompt)
        if profile == "choices":
            return next(line[0].lower() for line in prompt.splitlines() if ") End turn here" in line), None
        return fake(config, prompt, png)
    runner, _ = runner_for(tmp_path, table, model, timeout=10)
    path = runner.registry.path
    config = json.loads(path.read_text())
    config["providers"][0].update(prompt_profile=profile, primer=PRIMER, request_options={"max_tokens": 8192})
    path.write_text(json.dumps(config))
    assert runner.registry.load()["fake"]["primer"] == PRIMER
    runner.set_seat(mid, FOE, "MODEL", "fake")
    assert runner.drive(mid, max_steps=1) == 1
    assert sent and all(prompt.count(PRIMER) == 1 for prompt in sent)


def test_registry_accepts_maximum_primer_on_json_profiles(tmp_path):
    # A 1200-character primer needs a 4800-byte choices budget, because a seat style can run any row as choices.
    text = "x" * 1200
    for profile in ("full", "compact", "tiny"):
        loaded = _registry(tmp_path, _row(prompt_profile=profile, choices_bytes=4800, primer=text)).load()
        assert loaded["fake"]["primer"] == text


def test_registry_refuses_overlength_primer(tmp_path):
    with pytest.raises(ValueError, match="at most 1200 characters"):
        _registry(tmp_path, _row(prompt_profile="full", primer="x" * 1201)).load()


@pytest.mark.parametrize("bad", ["", "   ", "tab\there", "bell\x07", "line\u2028sep", "para\u2029sep", 7, ["list"]])
def test_registry_refuses_empty_or_unsafe_primer(tmp_path, bad):
    with pytest.raises(ValueError, match="primer"):
        _registry(tmp_path, _row(prompt_profile="full", primer=bad)).load()


def test_registry_refuses_primer_over_choices_budget_and_accepts_larger_budget(tmp_path):
    text = "x" * 400
    with pytest.raises(ValueError, match="choices_bytes budget"):
        _registry(tmp_path, _row(prompt_profile="choices", choices_bytes=800, primer=text)).load()
    loaded = _registry(tmp_path, _row(prompt_profile="choices", choices_bytes=4800, primer=text)).load()
    assert loaded["fake"]["primer"] == text


@pytest.mark.parametrize("profile", ["full", "compact", "tiny"])
def test_registry_refuses_primer_that_overflows_choices_when_seat_style_can_override(tmp_path, profile):
    # Regression: a seat may set style "choices" on any row, and a 400-character primer overflowed the 800-byte choices budget.
    with pytest.raises(ValueError, match="choices_bytes budget"):
        _registry(tmp_path, _row(prompt_profile=profile, choices_bytes=800, primer="x" * 400)).load()


def test_set_seat_style_override_refuses_overflowing_primer_at_registry_load(tmp_path):
    _, table, mid, *_ = fixture(tmp_path, "AIR_BASE_GATHER_CURRENT")
    runner, _ = runner_for(tmp_path, table, FakeProvider(), timeout=10)
    path = runner.registry.path
    config = json.loads(path.read_text())
    config["providers"][0].update(prompt_profile="full", choices_bytes=800, primer="x" * 400)
    path.write_text(json.dumps(config))
    with pytest.raises(ValueError, match="choices_bytes budget"):
        runner.set_seat(mid, FOE, "MODEL", "fake", style="choices")


def test_set_seat_style_override_dispatches_fitting_primer_once(tmp_path):
    _, table, mid, *_ = fixture(tmp_path, "AIR_BASE_GATHER_CURRENT")
    sent = []
    def model(config, prompt, png):
        sent.append(prompt)
        return next(line[0].lower() for line in prompt.splitlines() if ") End turn here" in line), None
    runner, _ = runner_for(tmp_path, table, model, timeout=10)
    path = runner.registry.path
    config = json.loads(path.read_text())
    primer = "x" * 150
    config["providers"][0].update(prompt_profile="full", choices_bytes=800, primer=primer)
    path.write_text(json.dumps(config))
    runner.set_seat(mid, FOE, "MODEL", "fake", style="choices")
    assert runner.drive(mid, max_steps=1) == 1
    assert sent and all(prompt.count(primer) == 1 and len(prompt.encode()) <= 800 for prompt in sent)


def test_registry_refuses_primer_for_d1_plain_over_choices_budget(tmp_path):
    with pytest.raises(ValueError, match="choices_bytes budget"):
        _registry(tmp_path, _row(id="d", kind="d1", base_url="http://127.0.0.1:1", choices_bytes=800,
                                 primer="x" * 400)).load()


def test_registry_still_rejects_unknown_row_fields(tmp_path):
    with pytest.raises(ValueError, match="never API keys"):
        _registry(tmp_path, _row(prompt_profile="full", primer="ok", surprise=1)).load()
