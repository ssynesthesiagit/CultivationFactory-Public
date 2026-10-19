"""Text decision endpoint adapter; legality and fallback remain with SeatRunner."""
import json
import math
import urllib.request

from .choices import decision_payload


def finite_number(value, minimum, maximum=None):
    if (isinstance(value, bool) or not isinstance(value, (int, float))
            or not math.isfinite(value) or value < minimum
            or (maximum is not None and value > maximum)):
        raise ValueError("Invalid decision confidence, probability or timing.")
    return value


def decide(provider, prompt):
    payload = decision_payload(prompt)
    request = urllib.request.Request(provider["base_url"].rstrip("/") + "/decide",
        data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=provider["timeout_s"]) as response:
        raw = response.read(1024 * 1024 + 1)
    if len(raw) > 1024 * 1024:
        raise ValueError("Decision reply is too large.")
    reply = json.loads(raw)
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
