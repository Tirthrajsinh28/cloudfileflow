from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_worker_compose_healthcheck_matches_background_process() -> None:
    compose = (PROJECT_ROOT / "compose.yaml").read_text(encoding="utf-8")
    worker_section = compose.split("  worker:", maxsplit=1)[1].split("\nvolumes:", maxsplit=1)[0]

    assert "healthcheck:" in worker_section
    assert "verify_database_revision" in worker_section
    assert "urllib.request.urlopen" not in worker_section
