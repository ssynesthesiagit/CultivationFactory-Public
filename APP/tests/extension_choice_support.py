"""Small helpers for choosing from a named bounded extension prompt in tests."""


def first_offered_option(prompt, reaction_source_id):
    """Return a legal option id, only when this exact prompt is being answered."""
    assert prompt["context"]["reaction_source_id"] == reaction_source_id
    options = prompt["choice"]["options"]
    assert options
    return options[0]["id"]


def offered_option(prompt, reaction_source_id, option_id):
    """Return a scenario's intended option after verifying this prompt offers it."""
    assert prompt["context"]["reaction_source_id"] == reaction_source_id
    assert option_id in {option["id"] for option in prompt["choice"]["options"]}
    return option_id


def answer_with_first_option(prompt, reaction_source_id, default):
    """Answer one named prompt from its offered options; preserve other answers."""
    if prompt["context"]["reaction_source_id"] == reaction_source_id:
        return [first_offered_option(prompt, reaction_source_id)]
    return default
