from pathlib import Path

def test_api_setup_is_not_inside_advanced_disclosure():
    html = (Path(__file__).resolve().parents[1] / "static/index.html").read_text()
    setup = html.index("<section id=\"guidedProviderSetup\"")
    advanced = html.index("<details id=\"guidedAdvancedAIOptions\"")
    assert setup < advanced, f"API setup at {setup}, advanced disclosure at {advanced}"
