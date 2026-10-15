from twin_chassis.testing import Tokens, assert_contract, test_settings

from app.main import SERVICE, build


def test_requests_match_the_contract():
    """contracts/openapi/catalog.v1.json is what the service really answers."""
    app = build(test_settings(SERVICE, "postgresql+psycopg://unused@127.0.0.1:1/unused"), Tokens().verifier())
    assert_contract(app, SERVICE)
