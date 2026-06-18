from pathlib import Path


def test_sample_fixture_content() -> None:
    sample_path = Path(__file__).parent / "agentic_demo" / "sample.txt"

    assert sample_path.read_text(encoding="utf-8") == "alpha\nbeta\ngamma\n"
