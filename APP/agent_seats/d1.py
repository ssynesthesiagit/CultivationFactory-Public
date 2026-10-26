"""Text decision endpoint adapter; legality and fallback remain with SeatRunner."""
import json
import math
import time
import urllib.error
import urllib.request

from .choices import decision_payload


def finite_number(value, minimum, maximum=None):
    if (isinstance(value, bool) or not isinstance(value, (int, float))
            or not math.isfinite(value) or value < minimum
            or (maximum is not None and value > maximum)):
        raise ValueError("Invalid decision confidence, probability or timing.")
    return value


# Same wording as tools/d1/d1_server.py, sent by the client when the owner's
# local AI app (protocol "local-app") hosts d1 and expects named questions.
INSTRUCTIONS = ("Choose the offered combat plan, follow-up, or reaction that best helps this fighter's team. "
                "Use only what the fighter perceives. Respect costs and fighting style. "
                "Turn plans end the turn; follow-ups and reactions resolve the current trigger. "
                "The table rechecks every action.")
APP_LIMIT = 6000  # the local AI app's CPU preset rejects larger state + questions
_tokens = {}


def _read(request, timeout):
    with urllib.request.urlopen(request, timeout=timeout) as response:
        raw = response.read(1024 * 1024 + 1)
    if len(raw) > 1024 * 1024:
        raise ValueError("Decision reply is too large.")
    return json.loads(raw)


def _app_reply(provider, payload):
    """Owner's local AI app: session token, then named questions; same answer shape."""
    base = provider["base_url"].rstrip("/")
    questions = {"action": {"type": "choice", "instructions": INSTRUCTIONS, "criteria": payload["options"]}}
    if len(json.dumps([payload["state"], questions])) > APP_LIMIT:
        raise ValueError("Decision state is too large for the local d1 app.")
    body = json.dumps({"state": payload["state"], "questions": questions}).encode()
    for attempt in (0, 1):
        if attempt or base not in _tokens:
            _tokens[base] = _read(urllib.request.Request(base + "/session"), provider["timeout_s"])["token"]
        request = urllib.request.Request(base + "/decide", data=body,
            headers={"Content-Type": "application/json", "X-D1-Token": _tokens[base]})
        started = time.perf_counter()
        try:
            answer = _read(request, provider["timeout_s"])["answers"]["action"]
        except urllib.error.HTTPError as exc:
            if exc.code == 403 and not attempt:
                continue  # the app was reloaded and issued a new session token
            raise
        return dict(answer, ms=(time.perf_counter() - started) * 1000)


def decide(provider, prompt):
    payload = decision_payload(prompt)
    if provider.get("protocol") == "local-app":
        reply = _app_reply(provider, payload)
    else:
        request = urllib.request.Request(provider["base_url"].rstrip("/") + "/decide",
            data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"})
        reply = _read(request, provider["timeout_s"])
    choice = reply.get("choice")
    if not isinstance(choice, str) or choice not in payload["options"]:
        raise ValueError("Decision reply selected an unoffered option.")
    probabilities = reply.get("probabilities")
    if not isinstance(probabilities, dict) or set(probabilities) != set(payload["options"]):
        raise ValueError("Decision reply probabilities must match the offered menu.")
    if not math.isclose(sum(finite_number(v, 0, 1) for v in probabilities.values()), 1, abs_tol=.02):
        raise ValueError("Decision reply probabilities must form a distribution.")
    metadata = {"choice": choice,
        "confidence": finite_number(reply.get("confidence"), 0, 1),
        "probabilities": {k: finite_number(v, 0, 1) for k, v in probabilities.items()},
        "ms": finite_number(reply.get("ms"), 0)}
    return choice, {"decision": metadata}
