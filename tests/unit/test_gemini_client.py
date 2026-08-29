from src.orchestrator.gemini_client import GeminiClient


def test_disabled_without_key(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    client = GeminiClient(api_key=None)
    assert client.enabled is False


def test_classify_intent_is_migration_cost(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    assert GeminiClient(api_key=None).classify_intent("cut my GCE bill") == "migration_cost"


def test_summarize_fallback_is_deterministic_and_mentions_step(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    client = GeminiClient(api_key=None)
    s1 = client.summarize_for_gate("proposal", {"savings_pct": 60})
    s2 = client.summarize_for_gate("proposal", {"savings_pct": 60})
    assert s1 == s2
    assert "proposal" in s1
    assert "60" in s1


def test_summarize_never_raises_on_bad_artifact(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    # Should not raise even if artifact is empty
    assert isinstance(GeminiClient(api_key=None).summarize_for_gate("deploy", {}), str)
