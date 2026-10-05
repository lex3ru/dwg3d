"""The API refuses to serve a site reachable by others with the development
secrets of .env.example."""
import pytest

DEV = {"DWG3D_SECRET": "dev-secret-change-me", "DWG3D_OIDC_CLIENT_SECRET": "dev-client-secret",
       "DWG3D_S3_SECRET_KEY": "dwg3d-secret"}


@pytest.fixture
def api(pg, monkeypatch):
    from dwg3d import api
    for k in (*DEV, "DWG3D_PUBLIC_URL", "DWG3D_ALLOW_WEAK_SECRETS"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setattr(api.db, "database_url", lambda: "postgresql+psycopg://dwg3d:s3cr3t@db/dwg3d")
    return api


def test_development_secrets_stop_a_public_site(api, monkeypatch):
    for k, v in DEV.items():
        monkeypatch.setenv(k, v)
    monkeypatch.setattr(api.db, "database_url", lambda: "postgresql+psycopg://dwg3d:dwg3d@db/dwg3d")
    assert sorted(api.weak_secrets()) == sorted([*DEV, "POSTGRES_PASSWORD"])
    monkeypatch.setenv("DWG3D_PUBLIC_URL", "https://plans.example.com")
    with pytest.raises(RuntimeError, match="DWG3D_SECRET"):
        api._check_secrets()
    monkeypatch.setenv("DWG3D_ALLOW_WEAK_SECRETS", "1")
    api._check_secrets()                                   # a test stand: only a warning


def test_localhost_only_warns(api, monkeypatch):
    monkeypatch.setenv("DWG3D_SECRET", "dev-secret-change-me")
    for url in (None, "http://localhost:8088", "http://127.0.0.1:5174", "http://app.localhost"):
        if url:
            monkeypatch.setenv("DWG3D_PUBLIC_URL", url)
        api._check_secrets()


def test_own_secrets_pass(api, monkeypatch):
    monkeypatch.setenv("DWG3D_PUBLIC_URL", "https://plans.example.com")
    monkeypatch.setenv("DWG3D_SECRET", "x" * 64)
    monkeypatch.setenv("DWG3D_OIDC_CLIENT_SECRET", "y" * 48)
    assert api.weak_secrets() == []
    api._check_secrets()
    monkeypatch.setenv("DWG3D_SECRET", "short")
    assert api.weak_secrets() == ["DWG3D_SECRET"]
