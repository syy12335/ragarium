from __future__ import annotations

import os
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
    def __init__(self, config_path: str = "config/application.yaml", secrets_path: str | Path | None = None) -> None:
        self.config = YamlConfigReader(config_path)
        self.app_path = self.config.config_path
        self.project_root = self.app_path.parent.parent
        self.roles_path = self.app_path.parent / "model_roles.yaml"
        self.secrets_path = Path(secrets_path) if secrets_path else self.project_root / "var" / "app" / "provider_keys.yaml"

    def read(self) -> Dict[str, Any]:
        app_cfg = _read_yaml(self.app_path)
        roles_cfg = _read_yaml(self.roles_path)
        ingestion_cfg = app_cfg.get("ingestion") or {}
        providers = app_cfg.get("llm") or {}
        self._load_managed_api_keys(providers)

        return {
            "providers": providers,
            "env_status": self._provider_env_status(providers),
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

    @staticmethod
    def _provider_env_status(providers: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
        statuses: Dict[str, Dict[str, Any]] = {}
        for key, provider in providers.items():
            if not isinstance(provider, dict):
                continue
            env_name = str(provider.get("api_key_env") or "").strip()
            statuses[key] = {
                "api_key_env": env_name,
                "configured": bool(env_name and os.environ.get(env_name)),
            }
        return statuses

    @staticmethod
    def _default_api_key_env(provider_key: str) -> str:
        normalized = "".join(char if char.isalnum() else "_" for char in provider_key.upper()).strip("_")
        return f"{normalized or 'PROVIDER'}_API_KEY"

    def _read_managed_api_keys(self) -> Dict[str, str]:
        data = _read_yaml(self.secrets_path)
        keys = data.get("api_keys") if isinstance(data.get("api_keys"), dict) else data
        if not isinstance(keys, dict):
            return {}
        return {
            str(provider).strip(): str(api_key)
            for provider, api_key in keys.items()
            if str(provider).strip() and str(api_key)
        }

    def _write_managed_api_keys(self, keys: Dict[str, str]) -> None:
        _write_yaml(self.secrets_path, {"api_keys": keys})

    def _load_managed_api_keys(self, providers: Dict[str, Any]) -> None:
        managed_keys = self._read_managed_api_keys()
        for provider_key, api_key in managed_keys.items():
            provider = providers.get(provider_key)
            if not isinstance(provider, dict):
                continue
            env_name = str(provider.get("api_key_env") or "").strip()
            if not env_name:
                env_name = self._default_api_key_env(provider_key)
                provider["api_key_env"] = env_name
            os.environ[env_name] = api_key

    def _save_payload_api_keys(self, providers: Dict[str, Any], api_keys: Dict[str, Any]) -> None:
        managed_keys = self._read_managed_api_keys()
        for provider_key, raw_api_key in api_keys.items():
            key = str(provider_key).strip()
            api_key = str(raw_api_key or "").strip()
            if not key or not api_key or key not in providers:
                continue
            provider = providers[key]
            env_name = str(provider.get("api_key_env") or "").strip()
            if not env_name:
                env_name = self._default_api_key_env(key)
                provider["api_key_env"] = env_name
            managed_keys[key] = api_key
            os.environ[env_name] = api_key
        self._write_managed_api_keys({key: value for key, value in managed_keys.items() if key in providers})

    def update(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        app_cfg = _read_yaml(self.app_path)
        roles_cfg = _read_yaml(self.roles_path)

        providers = payload.get("providers")
        if isinstance(providers, dict):
            providers = {
                str(key).strip(): value
                for key, value in providers.items()
                if str(key).strip() and isinstance(value, dict)
            }
            if not providers:
                raise ValueError("at least one provider is required")
            for provider_key, provider in providers.items():
                if not str(provider.get("api_key_env") or "").strip():
                    provider["api_key_env"] = self._default_api_key_env(provider_key)
            self._save_payload_api_keys(providers, payload.get("api_keys") or {})
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
