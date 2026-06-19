from pathlib import Path


def test_agentic_demo_sample_content():
    sample = Path(__file__).parent / "agentic_demo" / "sample.txt"
    assert sample.read_text(encoding="utf-8") == "alpha\nbeta\ngamma\n"
