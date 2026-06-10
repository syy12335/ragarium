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

    service = AppConfigService(str(app_path))
    updated = service.update(
        {
            "providers": {
                "qwen": {
                    "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
                    "api_key_env": "API_KEY_QWEN",
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
    assert updated["providers"]["qwen"]["api_key_env"] == "API_KEY_QWEN"
    assert updated["roles"]["answer"]["model_name"] == "qwen3.7-plus"
    assert updated["roles"]["judge"]["model_name"] == "qwen3.7-plus"
    assert updated["chunk"] == {"chunk_size": 700, "chunk_overlap": 80}
