from types import SimpleNamespace

from app import demo_plugin, mfa

DEMO = SimpleNamespace(email="Clinician@clarion.demo")
REAL = SimpleNamespace(email="dr.lim@hospital.my")


def test_exempt_only_in_demo_env(monkeypatch):
    monkeypatch.setenv("APP_ENV", "demo")
    assert demo_plugin.skips_mfa(DEMO) and not demo_plugin.skips_mfa(REAL)
    assert mfa.challenge_kind(DEMO) is None
    monkeypatch.setenv("APP_ENV", "production")
    assert not demo_plugin.skips_mfa(DEMO)
