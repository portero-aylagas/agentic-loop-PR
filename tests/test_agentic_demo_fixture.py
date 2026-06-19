from pathlib import Path


def test_agentic_demo_fixture_contents():
    fixture = Path(__file__).parent / "agentic_demo" / "sample.txt"
    assert fixture.read_text(encoding="utf-8") == "alpha\nbeta\ngamma\n"
