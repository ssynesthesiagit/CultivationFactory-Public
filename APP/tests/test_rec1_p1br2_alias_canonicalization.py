from __future__ import annotations

from copy import deepcopy

from character_creation import CharacterCreationExecutionService


class CapturingStage2:
    def __init__(self) -> None:
        self.created = None

    def create_proposal(self, proposal):
        self.created = deepcopy(proposal)
        return {"proposal_id": "stage2.proposal.rec1-p1br2"}

    def validate_proposal(self, proposal_id):
        return {"valid": True, "proposal_id": proposal_id}

    def issue_approval_challenge(self, proposal_id):
        return {"challenge_id": "challenge.rec1-p1br2", "nonce": "nonce.rec1-p1br2"}

    def approve_proposal(self, *args, **kwargs):
        return {"approved": True}

    def commit_proposal(self, proposal_id):
        return {"proposal_id": proposal_id, "committed": True}


def test_production_ingress_copies_and_canonicalizes_only_typed_stage2_kinds():
    proposal = {
        "schema_version": "TianxiaFoundry.Stage2AdvancementProposal.v2",
        "choices": [
            {
                "kind": "insight_acquisition",
                "record_id": "insight.legacy-qi-efficiency",
                "effective_cl": 4,
                "acquisition_channel": "cultivation-insight-selection",
                "parameters": {"ability": "INT", "amount": 1, "repeat_index": 1},
            },
            {"kind": "cultivation_insight_acquisition", "record_id": "canonical"},
            {"kind": "origin_insight_acquisition", "record_id": "origin"},
            {"kind": "unknown_kind", "record_id": "unknown", "display": "insight_acquisition"},
        ],
        "diagnostic": "insight_acquisition remains prose here",
    }
    before = deepcopy(proposal)
    stage2 = CapturingStage2()
    execution = CharacterCreationExecutionService(
        None,
        stage1=None,
        provider=None,
        project_store=None,
        stage2=stage2,
        owner_principal="owner",
    )

    validation, commit = execution._stage2_commit(stage2, proposal, "owner")

    assert validation["valid"] is True
    assert commit["committed"] is True
    assert proposal == before
    assert stage2.created["choices"][0]["kind"] == "cultivation_insight_acquisition"
    assert stage2.created["choices"][1]["kind"] == "cultivation_insight_acquisition"
    assert stage2.created["choices"][2]["kind"] == "origin_insight_acquisition"
    assert stage2.created["choices"][3]["kind"] == "unknown_kind"
    assert stage2.created["choices"][3]["display"] == "insight_acquisition"
    assert stage2.created["diagnostic"] == "insight_acquisition remains prose here"
