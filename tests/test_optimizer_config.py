from __future__ import annotations

from pathlib import Path

from azure.ai.agentserver.optimization import load_config

AGENT_ROOT = Path(__file__).parents[1] / "agents" / "hosted"


def test_official_optimizer_baseline_loads(monkeypatch) -> None:
    monkeypatch.chdir(AGENT_ROOT)
    monkeypatch.delenv("OPTIMIZATION_CONFIG", raising=False)
    monkeypatch.delenv("OPTIMIZATION_CANDIDATE_ID", raising=False)
    monkeypatch.delenv("OPTIMIZATION_RESOLVE_ENDPOINT", raising=False)
    config = load_config(config_dir=AGENT_ROOT / ".agent_configs")
    assert config is not None
    assert config.model == "gpt-5.4-mini"
    assert "ST Incident Commander" in config.instructions
    assert config.source.endswith(".agent_configs\\baseline")
