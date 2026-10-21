"""Private diagnostic requested by BONUSFIX1: ONLY a disposable owner-match copy.

Temporary lane evidence, not a public regression. No reads/writes to live data.
"""
import json
from pathlib import Path
import shutil
import subprocess

import pytest

from combat.gate5_service import CombatService
from app.api import create_app
from app.core import Settings
from tests.async_support import run_asgi
import httpx

ROOT = Path(__file__).resolve().parents[1]
COPY = Path("/var/tmp/auto-audit/wt-bonus-actions-1/bonusfix-scratch")
MID = "match:8c180e453d256439be6a4d70"


@pytest.mark.parametrize("name", ["Ruin Channel", "Black-Claw Manifestation"])
def test_actual_copy_expansion_and_commit(tmp_path, monkeypatch, capsys, name):
    monkeypatch.setenv("CF_EMBED_MENU", "0")
    shutil.copytree(COPY, tmp_path, dirs_exist_ok=True)
    app = create_app(Settings.from_env(ROOT, tmp_path))
    app.state.agent_seats.background = False
    table = app.state.agent_seats.table
    combat = table.combat

    async def request(method, path, **kwargs):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
            base_url="http://scratch.test", headers={"x-foundry-token": app.state.session_token}) as client:
            reply = await client.request(method, f"/api/tabletop/matches/{MID}" + path, **kwargs)
            assert reply.status_code == 200, reply.text
            return reply.json()

    # Real application routes on an in-process, disposable ASGI scratch server.
    http_state = run_asgi(request("GET", "/state", params={"compact": "true"}))
    assert http_state["menu"]["lazy"]
    state = table.state(MID, lazy=True)
    menu = state["menu"]
    group = next(g for g in menu["actions"] if g["label"].startswith(name)
                 and (name == "Ruin Channel" or "(1 Stamina)" in g["label"] and "Bonus Damage" in g["label"]))
    assert group.get("lazy") and not group["options"], group
    expansion = run_asgi(request("GET", "/action-options", params={
        "source": group["source_definition_id"], "decision_id": menu["decision_id"],
        "state_version": menu["state_version"]}))
    expanded = next(g for g in expansion["actions"] if g["source_definition_id"] == group["source_definition_id"])
    assert len(expanded["options"]) == 1
    assert expanded["options"][0]["target_ids"] == [menu["actor_id"]]
    # Exercise the production browser chooser with exactly the private server
    # response, then submit only what that chooser selected on this copy.
    script = r"""
      import assert from 'node:assert/strict';
      import {readFileSync} from 'node:fs';
      let input=''; for await (const part of process.stdin) input+=part;
      const {menu,group,expansion,oldSource} = JSON.parse(input);
      const app={matchId:'copy',menu}, calls=[], hints=[];
      const env={app,URLSearchParams,enc:encodeURIComponent,api:async()=>expansion,
        toast(){},refuseCoveredView:()=>false,actOnce:id=>{calls.push(id);return true;},
        hint:text=>hints.push(text),renderHighlights(){},broadcastActors(){}};
      const extract=(source)=>{
        let start=source.indexOf('function useGroup(');
        if(source.slice(start-6,start)==='async ')start-=6;
        return source.slice(start,source.indexOf('\n}',start)+2);
      };
      const run=(source)=>new Function(...Object.keys(env),extract(source)+';return useGroup;')(...Object.values(env));
      void run(oldSource)(structuredClone(group));
      assert.ok(app.targeting, 'old already-open client must reproduce the blank map');
      assert.match(hints.at(-1), /: choose $/);
      const oldPrompt=hints.at(-1);
      app.targeting=null;app.pendingChoice=null;
      const current=readFileSync('static/tabletop/tabletop.js','utf8');
      assert.equal(await run(current)(structuredClone(group)),true);
      assert.equal(app.targeting,null);
      assert.equal(app.pendingChoice,null);
      console.log(JSON.stringify({candidate_id:calls[0],oldPrompt,requests:1}));
    """
    selected = subprocess.run(["node", "--input-type=module", "-e", script],
        cwd=ROOT, input=json.dumps({"menu": menu, "group": group, "expansion": expansion,
                                   "oldSource": (COPY / "pre_lazy_tabletop.js").read_text()}),
        capture_output=True, text=True, timeout=45)
    assert selected.returncode == 0, selected.stdout + selected.stderr
    result = json.loads(selected.stdout)
    assert result["candidate_id"] == expanded["options"][0]["candidate_id"]
    payload = {"candidate_id": result["candidate_id"], "decision_id": menu["decision_id"],
               "state_version": menu["state_version"], "after": state["last_sequence"]}
    reply = run_asgi(request("POST", "/act", json=payload))
    answers = []
    for _ in range(12):
        if reply["status"] == "COMMITTED":
            break
        assert reply["status"] == "REACTION_REQUIRED", reply
        prompt = reply["reaction"]
        options = (prompt.get("choice") or {}).get("options", [])
        answer = {**prompt["context"], "selection": "USE" if options else "DECLINE"}
        if options:
            answer["option_ids"] = [options[0]["id"]]
        answers.append(answer)
        reply = run_asgi(request("POST", "/act", json={**payload, "reactions": answers}))
    assert reply["status"] == "COMMITTED", reply
    fresh = CombatService(ROOT, tmp_path)._load_session(MID).engine
    actor = fresh.state.actors[menu["actor_id"]]
    assert not actor.bonus_action_available
    assert fresh.state.state_version > menu["state_version"]
    conditions = [c.condition_id for c in actor.conditions.values()]
    assert any(("ruin_channel" if name == "Ruin Channel" else "black_claw") in c for c in conditions), conditions
    with capsys.disabled():
        print(json.dumps({"name": name, "oldPrompt": result["oldPrompt"],
                          "status": reply["status"], "version": fresh.state.state_version,
                          "conditions": conditions}), flush=True)
