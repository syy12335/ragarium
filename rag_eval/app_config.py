from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

import yaml

from utils import YamlConfigReader


DEFAULT_CHUNK_SIZE = 900
DEFAULT_CHUNK_OVERLAP = 120


def _read_yaml(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as file:
        data = yaml.safe_load(file)
    return data if isinstance(data, dict) else {}


def _write_yaml(path: Path, data: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file:
        yaml.safe_dump(data, file, allow_unicode=True, sort_keys=False)


class AppConfigService:
    def __init__(self, config_path: str = "config/application.yaml") -> None:
        self.config = YamlConfigReader(config_path)
        self.app_path = self.config.config_path
        self.project_root = self.app_path.parent.parent
        self.roles_path = self.app_path.parent / "model_roles.yaml"

    def read(self) -> Dict[str, Any]:
        app_cfg = _read_yaml(self.app_path)
        roles_cfg = _read_yaml(self.roles_path)
        ingestion_cfg = app_cfg.get("ingestion") or {}

        return {
            "providers": app_cfg.get("llm") or {},
            "roles": {
                "embedding": roles_cfg.get("embedding") or {},
                "answer": roles_cfg.get("generation") or {},
                "judge": roles_cfg.get("evaluation") or {},
            },
            "chunk": {
                "chunk_size": int(ingestion_cfg.get("chunk_size") or DEFAULT_CHUNK_SIZE),
                "chunk_overlap": int(ingestion_cfg.get("chunk_overlap") or DEFAULT_CHUNK_OVERLAP),
            },
        }

    def update(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        app_cfg = _read_yaml(self.app_path)
        roles_cfg = _read_yaml(self.roles_path)

        providers = payload.get("providers")
        if isinstance(providers, dict):
            app_cfg["llm"] = providers

        chunk = payload.get("chunk") or {}
        chunk_size = int(chunk.get("chunk_size") or DEFAULT_CHUNK_SIZE)
        chunk_overlap = int(chunk.get("chunk_overlap") or DEFAULT_CHUNK_OVERLAP)
        if chunk_size <= 0:
            raise ValueError("chunk_size must be positive")
        if chunk_overlap < 0 or chunk_overlap >= chunk_size:
            raise ValueError("chunk_overlap must be >= 0 and smaller than chunk_size")
        app_cfg["ingestion"] = {
            "chunk_size": chunk_size,
            "chunk_overlap": chunk_overlap,
        }

        roles = payload.get("roles") or {}
        if isinstance(roles.get("embedding"), dict):
            roles_cfg["embedding"] = roles["embedding"]
        if isinstance(roles.get("answer"), dict):
            roles_cfg["generation"] = roles["answer"]
        if isinstance(roles.get("judge"), dict):
            roles_cfg["evaluation"] = roles["judge"]

        _write_yaml(self.app_path, app_cfg)
        _write_yaml(self.roles_path, roles_cfg)
        return self.read()
