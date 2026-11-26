"""Shared Technique-Closing Point fight setup for the C14 rider and review tests."""
from pathlib import Path

from tests import test_riders_c2 as C2

ROOT = Path(__file__).resolve().parents[1]
CLOSING = C2.PP + "technique_closing_point"


def closing_fight(save):
    engine = C2._fight(C2._pp([CLOSING], dc=50), attacker=True)
    atk = C2._ready(engine, C2.ATK)
    C2._act(engine, "Calming Heart Pill", actor_id=C2.ATK)
    C2._ready(engine, C2.ME)
    C2._pick(engine, "Technique-Closing Point")
    C2._mark(engine, C2.ATK, name="Pressure Point")
    atk.saving_throws["CON"] = atk.saving_throws["WIS"] = save
    events = C2._press(engine, C2.ATK)
    return engine, atk, events
