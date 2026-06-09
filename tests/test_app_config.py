from __future__ import annotations

import yaml

from rag_eval.app_config import AppConfigService


def test_app_config_reads_and_updates_provider_roles_and_chunk(tmp_path):
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
                        "api_key_env": "API_KEY_QWEN",
                        "default_model_name": "qwen-plus",
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
                "generation": {"provider": "qwen", "model_name": "qwen-flash"},
                "evaluation": {"provider": "qwen", "model_name": "qwen-plus"},
            },
            allow_unicode=True,
        ),
        encoding="utf-8",
    )

    service = AppConfigService(str(app_path))
    updated = service.update(
        {
            "providers": {
                "openai": {
                    "base_url": "https://api.openai.com/v1",
                    "api_key_env": "OPENAI_API_KEY",
                    "default_model_name": "gpt-4.1-mini",
                }
            },
            "roles": {
                "embedding": {"provider": "openai", "model_name": "text-embedding-3-small"},
                "answer": {"provider": "openai", "model_name": "gpt-4.1-mini"},
                "judge": {"provider": "openai", "model_name": "gpt-4.1"},
            },
            "chunk": {"chunk_size": 700, "chunk_overlap": 80},
        }
    )

    assert updated["providers"]["openai"]["api_key_env"] == "OPENAI_API_KEY"
    assert updated["roles"]["answer"]["model_name"] == "gpt-4.1-mini"
    assert updated["roles"]["judge"]["model_name"] == "gpt-4.1"
    assert updated["chunk"] == {"chunk_size": 700, "chunk_overlap": 80}
