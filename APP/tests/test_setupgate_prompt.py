"""Public Node regression for the table's pre-turn setup prompt."""
import subprocess
from pathlib import Path


def test_fight_setup_prompt_node():
    app = Path(__file__).resolve().parents[1]
    subprocess.run(["node", "--test", "static/tabletop/fight-setup-prompt.test.mjs"],
                   cwd=app, check=True, timeout=30)
