# ragarium/embeddings/factory.py

from __future__ import annotations

import os
from pathlib import Path
from typing import Final

from langchain_core.embeddings import Embeddings
from langchain_community.embeddings import DashScopeEmbeddings

from utils import YamlConfigReader, ensure_yaml_config_file


def _get_project_root(config: YamlConfigReader) -> Path:
    """
    约定：application.yaml 位于 project-root/config/application.yaml，
    因此 project-root = config.config_path.parent.parent
    """
    return config.config_path.parent.parent


def _load_model_roles_config(app_config: YamlConfigReader) -> YamlConfigReader:
    """
    从 project-root/config/model_roles.yaml 加载角色配置。
    """
    project_root = _get_project_root(app_config)
    roles_path = ensure_yaml_config_file(project_root / "config" / "model_roles.yaml")

    if not roles_path.exists():
        raise FileNotFoundError(
            f"[embedding_factory] 未找到 model_roles.yaml：{roles_path}，"
            "请确保文件存在并包含 embedding 段落。"
        )

    return YamlConfigReader(str(roles_path))


def build_embedding_from_config(app_config: YamlConfigReader) -> Embeddings:
    """
    根据 application.yaml + model_roles.yaml 构造一个 Embeddings 对象。

    新的配置约定：

    1）application.yaml 只负责厂商级别配置：

        llm:
          qwen:
            base_url: "https://dashscope.aliyuncs.com/compatible-mode/v1"
            api_key_env: "API_KEY_QWEN"
            default_model_name: "qwen3.7-plus"
          ...

    2）model_roles.yaml 负责“角色 → provider → model_name”映射：

        embedding:
          provider: "qwen"              # 指向 application.yaml 中 llm.qwen
          model_name: "text-embedding-v4"

    行为：

        1）从 model_roles.yaml 中读取 embedding.provider 和 embedding.model_name。
        2）根据 provider 去 application.yaml 的 llm.<provider> 读取 api_key_env。
        3）目前仅支持 provider == "qwen"（DashScopeEmbeddings），其他 provider 显式抛错。
    """
    # 1. 加载角色配置
    roles_config = _load_model_roles_config(app_config)

    provider_key = roles_config.get("embedding.provider")
    if not provider_key:
        raise ValueError("[embedding_factory] 配置缺少 embedding.provider（model_roles.yaml）")

    model_name = roles_config.get("embedding.model_name")
    if not model_name:
        raise ValueError("[embedding_factory] 配置缺少 embedding.model_name（model_roles.yaml）")

    # 2. 从 application.yaml 中读取对应 provider 的 llm 配置
    llm_section = app_config.get(f"llm.{provider_key}")
    if not llm_section:
        raise ValueError(
            f"[embedding_factory] 在 application.yaml 中未找到 llm.{provider_key} 段落，"
            "请确保 provider 与 llm.* 的键一致。"
        )

    api_key_env = llm_section.get("api_key_env")
    if not api_key_env:
        raise ValueError(
            f"[embedding_factory] 配置 llm.{provider_key} 缺少 api_key_env 字段，"
            "请在 application.yaml 中补全。"
        )

    api_key = os.environ.get(api_key_env)
    if not api_key:
        raise ValueError(
            f"[embedding_factory] 未在环境变量 {api_key_env} 中找到 API Key，"
            f"请先设置环境变量 {api_key_env}"
        )

    # 3. 按 provider_key 构造具体的 Embeddings 实现
    # 当前只支持 Qwen / DashScope，其他 provider 显式报错。
    if provider_key == "qwen":
        return DashScopeEmbeddings(
            model=model_name,
            dashscope_api_key=api_key,
        )

        # --------------------------------------------------------
        # 新增：OpenAI Embedding 支持（strict append, 无任何删改）
        # --------------------------------------------------------
    if provider_key == "openai":
        from langchain_openai import OpenAIEmbeddings

        return OpenAIEmbeddings(
            model=model_name,
            api_key=api_key,
        )
        # --------------------------------------------------------

    raise ValueError(
        f"[embedding_factory] 暂不支持 embedding.provider = {provider_key!r}，"
        "目前仅支持 provider = 'qwen'（DashScopeEmbeddings）。"
    )
