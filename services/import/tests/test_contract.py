from twin_chassis.testing import Tokens, assert_contract, test_settings

from app.main import SERVICE, build


def test_requests_match_the_contract():
    """contracts/openapi/import.v1.json is what the service really answers."""
    app = build(test_settings(SERVICE, "postgresql+psycopg://unused@127.0.0.1:1/unused"), Tokens().verifier())
    assert_contract(app, SERVICE)


def test_pipeline_is_the_one_of_the_single_application_version():
    """app/dwg recognises drawings exactly as legacy/ does: the modules are the same files.
    (docs/ACCEPTANCE.md, stage 1: floors, rooms and areas match the current version.)"""
    from pathlib import Path

    import pytest

    ours = Path(__file__).resolve().parents[1] / "app" / "dwg"
    theirs = Path(__file__).resolve().parents[3] / "legacy" / "backend" / "dwg3d"
    if not theirs.is_dir():
        pytest.skip("legacy/ is not here")
    for module in sorted(ours.glob("*.py")) + [ours / "default_config.yaml"]:
        if module.name != "__init__.py":
            assert module.read_bytes() == (theirs / module.name).read_bytes(), f"{module.name} differs from legacy/"
