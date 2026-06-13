# ragarium/rag/normal_rag.py

from typing import Any, Dict, List, Optional
import os

from langchain_core.documents import Document
from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI

from utils import YamlConfigReader


class NormalRag:
    """
    单库 RAG 工作流（尽量简单版本）：

      retriever 由 VectorStoreManager 提供；
      模型和提示词统一从：
        1）config/application.yaml 的 llm.<provider>
        2）config/model_roles.yaml 的 generation
      中读取。
    """

    def __init__(
        self,
        retriever: Any,
        config_path: str = "config/application.yaml",
        prompt_text: Optional[str] = None,
    ) -> None:
        self.retriever = retriever

        # 读取两个配置文件：application.yaml 与 model_roles.yaml
        app_cfg = YamlConfigReader(config_path)
        roles_cfg = YamlConfigReader("config/model_roles.yaml")

        gen_cfg: Dict[str, Any] = roles_cfg.get("generation") or {}
        if not gen_cfg:
            raise ValueError("model_roles.yaml 中缺少 generation 段落")

        provider = gen_cfg.get("provider")
        if not provider:
            raise ValueError("generation.provider 不能为空")

        provider_cfg: Dict[str, Any] = app_cfg.get(f"llm.{provider}") or {}
        if not provider_cfg:
            raise ValueError(f"application.yaml 中未找到 llm.{provider} 配置")

        base_url = provider_cfg.get("base_url")
        api_key_env = provider_cfg.get("api_key_env")
        default_model_name = provider_cfg.get("default_model_name")

        if not base_url or not api_key_env:
            raise ValueError(f"llm.{provider} 缺少 base_url 或 api_key_env")

        # 模型名：优先用 generation.model_name / generation.model，其次用厂商默认
        model_name = (
            gen_cfg.get("model_name")
            or gen_cfg.get("model")
            or default_model_name
        )
        if not model_name:
            raise ValueError("generation.model_name 为空且未提供厂商默认模型名")

        api_key = os.environ.get(api_key_env)
        if not api_key:
            raise RuntimeError(f"环境变量 {api_key_env} 未设置")

        temperature = float(gen_cfg.get("temperature", 0.0))
        max_tokens_raw = gen_cfg.get("max_tokens")
        max_tokens: Optional[int] = (
            int(max_tokens_raw) if max_tokens_raw is not None else None
        )
        timeout = int(provider_cfg.get("timeout", 60))

        # 1）构造 LLM（统一视为 OpenAI 兼容接口）
        self.llm = ChatOpenAI(
            base_url=base_url,
            model=model_name,
            api_key=api_key,
            temperature=temperature,
            max_tokens=max_tokens,
            timeout=timeout,
        )

        # 2）构造 Prompt：直接把 YAML 里的 prompt 塞进 template
        if not prompt_text:
            prompt_text = gen_cfg.get("prompt") or (
                "问题：{question}\n\n"
                "上下文：\n{contexts}\n\n"
                "记忆：{memory_text}"
            )
        self.prompt = ChatPromptTemplate.from_template(prompt_text)

    def invoke(self, question: str) -> Dict[str, Any]:
        """
        执行一次 RAG
        """
        # 1）检索上下文（新版接口）
        docs: List[Document] = self.retriever.invoke(question)

        contexts_text = "\n\n".join(d.page_content for d in docs)
        memory_text = ""

        messages = self.prompt.format_messages(
            question=question,
            contexts=contexts_text,
            memory_text=memory_text,
        )

        llm_output = self.llm.invoke(messages)
        answer_text = getattr(llm_output, "content", str(llm_output))

        contexts = [
            {
                "content": d.page_content,
                "metadata": d.metadata or {},
            }
            for d in docs
        ]

        return {
            "question": question,
            "answer": answer_text,
            "contexts": contexts,
        }
