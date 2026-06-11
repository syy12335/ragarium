from __future__ import annotations

import yaml
import pytest

from rag_eval.app_config import AppConfigService


def test_app_config_reads_and_updates_provider_roles_and_chunk(tmp_path, monkeypatch):
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    app_path = config_dir / "application.yaml"
    roles_path = config_dir / "model_roles.yaml"
    app_path.write_text(
        yaml.safe_dump(
            {
                "llm": {
                    "qwen": {
                        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
                        "api_key_env": "TEST_APP_CONFIG_QWEN_KEY",
                        "default_model_name": "qwen3.7-plus",
                    }
                }
            },
            allow_unicode=True,
        ),
        encoding="utf-8",
    )
    roles_path.write_text(
        yaml.safe_dump(
            {
                "embedding": {"provider": "qwen", "model_name": "text-embedding-v4"},
                "generation": {"provider": "qwen", "model_name": "qwen3.7-plus"},
                "evaluation": {"provider": "qwen", "model_name": "qwen3.7-plus"},
            },
            allow_unicode=True,
        ),
        encoding="utf-8",
    )

    monkeypatch.delenv("TEST_APP_CONFIG_QWEN_KEY", raising=False)
    service = AppConfigService(str(app_path))
    updated = service.update(
        {
            "providers": {
                "qwen": {
                    "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
                    "api_key_env": "TEST_APP_CONFIG_QWEN_KEY",
                    "default_model_name": "qwen3.7-plus",
                }
            },
            "roles": {
                "embedding": {"provider": "qwen", "model_name": "text-embedding-v4"},
                "answer": {"provider": "qwen", "model_name": "qwen3.7-plus"},
                "judge": {"provider": "qwen", "model_name": "qwen3.7-plus"},
            },
            "chunk": {"chunk_size": 700, "chunk_overlap": 80},
        }
    )

    assert list(updated["providers"]) == ["qwen"]
    assert updated["providers"]["qwen"]["api_key_env"] == "TEST_APP_CONFIG_QWEN_KEY"
    assert updated["env_status"]["qwen"] == {"api_key_env": "TEST_APP_CONFIG_QWEN_KEY", "configured": False}
    assert updated["roles"]["answer"]["model_name"] == "qwen3.7-plus"
    assert updated["roles"]["judge"]["model_name"] == "qwen3.7-plus"
    assert updated["chunk"] == {"chunk_size": 700, "chunk_overlap": 80}


def test_app_config_reports_provider_env_status(tmp_path, monkeypatch):
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    app_path = config_dir / "application.yaml"
    (config_dir / "model_roles.yaml").write_text("{}", encoding="utf-8")
    app_path.write_text(
        yaml.safe_dump(
            {
                "llm": {
                    "qwen": {
                        "api_key_env": "TEST_APP_CONFIG_STATUS_KEY",
                    }
                }
            },
            allow_unicode=True,
        ),
        encoding="utf-8",
    )

    monkeypatch.delenv("TEST_APP_CONFIG_STATUS_KEY", raising=False)
    service = AppConfigService(str(app_path))
    assert service.read()["env_status"]["qwen"]["configured"] is False

    monkeypatch.setenv("TEST_APP_CONFIG_STATUS_KEY", "test-key")
    assert service.read()["env_status"]["qwen"]["configured"] is True


def test_app_config_manages_api_keys_in_local_secret_file(tmp_path, monkeypatch):
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    app_path = config_dir / "application.yaml"
    (config_dir / "model_roles.yaml").write_text("{}", encoding="utf-8")
    app_path.write_text(
        yaml.safe_dump(
            {
                "llm": {
                    "qwen": {
                        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
                        "api_key_env": "API_KEY_QWEN",
                        "default_model_name": "qwen3.7-plus",
                    }
                }
            },
            allow_unicode=True,
        ),
        encoding="utf-8",
    )
    secrets_path = tmp_path / "var" / "app" / "provider_keys.yaml"
    monkeypatch.delenv("API_KEY_QWEN", raising=False)

    service = AppConfigService(str(app_path), secrets_path=secrets_path)
    updated = service.update(
        {
            "providers": {
                "qwen": {
                    "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
                    "api_key_env": "API_KEY_QWEN",
                    "default_model_name": "qwen3.7-plus",
                }
            },
            "roles": {},
            "chunk": {"chunk_size": 900, "chunk_overlap": 120},
            "api_keys": {"qwen": "secret-key"},
        }
    )

    assert updated["env_status"]["qwen"]["configured"] is True
    assert updated["providers"]["qwen"].get("api_key") is None
    assert yaml.safe_load(secrets_path.read_text(encoding="utf-8")) == {"api_keys": {"qwen": "secret-key"}}

    monkeypatch.delenv("API_KEY_QWEN", raising=False)
    restored = AppConfigService(str(app_path), secrets_path=secrets_path).read()
    assert restored["env_status"]["qwen"]["configured"] is True
    assert restored["providers"]["qwen"].get("api_key") is None


def test_app_config_rejects_empty_providers(tmp_path):
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    app_path = config_dir / "application.yaml"
    (config_dir / "model_roles.yaml").write_text("{}", encoding="utf-8")
    app_path.write_text(
        yaml.safe_dump(
            {
                "llm": {
                    "qwen": {
                        "api_key_env": "API_KEY_QWEN",
                    }
                }
            },
            allow_unicode=True,
        ),
        encoding="utf-8",
    )

    service = AppConfigService(str(app_path))

    with pytest.raises(ValueError, match="at least one provider"):
        service.update({"providers": {}, "roles": {}, "chunk": {"chunk_size": 900, "chunk_overlap": 120}})
