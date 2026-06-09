from __future__ import annotations

import json
import os
import re
from typing import Any, Callable, Dict, List, Optional

from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI

from rag_eval.storage import ProductStore
from utils import YamlConfigReader


ModelClient = Callable[[str], str]


class QueryGenerationService:
    def __init__(
        self,
        store: ProductStore,
        *,
        config_path: str = "config/application.yaml",
        model_client: Optional[ModelClient] = None,
    ) -> None:
        self.store = store
        self.config_path = config_path
        self.model_client = model_client

    @staticmethod
    def validate_examples(examples: List[str]) -> List[str]:
        cleaned = [example.strip() for example in examples if example and example.strip()]
        if len(cleaned) < 3 or len(cleaned) > 5:
            raise ValueError("query generation requires 3 to 5 example queries")
        return cleaned

    @staticmethod
    def parse_queries(raw: str) -> List[str]:
        text = raw.strip()
        fenced = re.search(r"```(?:json)?\s*(.*?)```", text, flags=re.S)
        if fenced:
            text = fenced.group(1).strip()
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            start = text.find("[")
            end = text.rfind("]")
            if start == -1 or end == -1 or end < start:
                raise ValueError("model response is not a JSON array")
            payload = json.loads(text[start : end + 1])

        if not isinstance(payload, list):
            raise ValueError("model response must be a JSON array")
        queries = []
        seen = set()
        for item in payload:
            query = str(item).strip()
            if not query or query in seen:
                continue
            queries.append(query)
            seen.add(query)
        return queries

    def generate(
        self,
        *,
        knowledge_base_id: int,
        examples: List[str],
        target_count: int,
        name: str = "Generated queries",
        sample_chunk_limit: int = 16,
    ) -> Dict[str, Any]:
        examples = self.validate_examples(examples)
        if target_count <= 0:
            raise ValueError("target_count must be positive")

        chunks = self.store.list_chunks(knowledge_base_id, limit=sample_chunk_limit)
        if not chunks:
            raise ValueError("knowledge base has no chunks; import and index data first")

        context = "\n\n".join(
            f"[{idx + 1}] {chunk['content'][:1200]}"
            for idx, chunk in enumerate(chunks)
            if chunk.get("content")
        )
        prompt = self._build_prompt(
            examples=examples,
            target_count=target_count,
            context=context,
        )
        raw = self._call_model(prompt)
        queries = self.parse_queries(raw)
        if len(queries) < target_count:
            raise ValueError(
                f"model returned {len(queries)} unique queries, fewer than requested {target_count}"
            )
        queries = queries[:target_count]
        return self.store.create_query_set(
            knowledge_base_id,
            name=name,
            examples=examples,
            target_count=target_count,
            queries=queries,
        )

    @staticmethod
    def _build_prompt(*, examples: List[str], target_count: int, context: str) -> str:
        example_text = "\n".join(f"- {example}" for example in examples)
        return (
            "You generate evaluation queries for a RAG knowledge base.\n"
            "Use the knowledge-base content as the factual domain and imitate the style of the examples.\n"
            "Return only a JSON array of strings. Do not include answers or explanations.\n\n"
            f"Target count: {target_count}\n\n"
            f"Example queries:\n{example_text}\n\n"
            f"Knowledge-base excerpts:\n{context}\n"
        )

    def _call_model(self, prompt: str) -> str:
        if self.model_client is not None:
            return self.model_client(prompt)

        app_cfg = YamlConfigReader(self.config_path)
        roles_cfg = YamlConfigReader(str(app_cfg.config_path.parent / "model_roles.yaml"))
        gen_cfg: Dict[str, Any] = roles_cfg.get("query_generation") or roles_cfg.get("generation") or {}
        provider = gen_cfg.get("provider")
        if not provider:
            raise ValueError("query_generation/generation.provider is required")
        provider_cfg = app_cfg.get(f"llm.{provider}") or {}
        api_key_env = provider_cfg.get("api_key_env")
        base_url = provider_cfg.get("base_url")
        if not api_key_env or not base_url:
            raise ValueError(f"llm.{provider} must define base_url and api_key_env")
        api_key = os.environ.get(api_key_env)
        if not api_key:
            raise RuntimeError(f"environment variable {api_key_env} is not set")

        model_name = gen_cfg.get("model_name") or gen_cfg.get("model") or provider_cfg.get("default_model_name")
        llm = ChatOpenAI(
            base_url=base_url,
            api_key=api_key,
            model=model_name,
            temperature=float(gen_cfg.get("temperature", 0.3)),
            max_tokens=int(gen_cfg.get("max_tokens", 2048)),
        )
        prompt_template = ChatPromptTemplate.from_template("{prompt}")
        result = llm.invoke(prompt_template.format_messages(prompt=prompt))
        return getattr(result, "content", str(result))
