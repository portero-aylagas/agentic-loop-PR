from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_agentic_demo_sample_content():
    sample = ROOT / "tests" / "agentic_demo" / "sample.txt"
    assert sample.read_text(encoding="utf-8") == "alpha\nbeta\ngamma\n"
