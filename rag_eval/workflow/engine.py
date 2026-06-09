from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Callable, Dict, Iterable, List, Optional

from rag_eval.rag.normal_rag import NormalRag


OFFLINE_DB_TEMPLATE_ID = "offline_db"
RAG_TEMPLATE_ID = "rag"
EVALUATION_TEMPLATE_ID = "evaluation"
LEGACY_FULL_RAG_TEMPLATE_ID = "legacy_full_rag"
DEFAULT_TEMPLATE_ID = RAG_TEMPLATE_ID

LEGACY_FULL_RAG_NODE_TYPES = [
    "source",
    "parse",
    "chunk",
    "embed_index",
    "retrieve",
    "prompt_llm",
    "answer",
]


def _node(node_id: str, node_type: str, x: int, y: int, data: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": node_id,
        "type": node_type,
        "position": {"x": x, "y": y},
        "data": data,
    }


def _edge(source: str, target: str) -> Dict[str, str]:
    return {"id": f"{source}-{target}", "source": source, "target": target}


DEFAULT_WORKFLOW_GRAPH: Dict[str, Any] = {
    "nodes": [
        _node("source", "source", 0, 120, {"label": "Source DB", "knowledgeBaseId": ""}),
        _node("parse", "parse", 180, 120, {"label": "Parse", "parser": "auto"}),
        _node("chunk", "chunk", 360, 120, {"label": "Chunk", "chunkSize": 900, "chunkOverlap": 120}),
        _node("embed", "embed_index", 540, 120, {"label": "Embed / Index", "collection": "selected_knowledge_base"}),
        _node("retrieve", "retrieve", 720, 120, {"label": "Retrieve", "topK": 3, "knowledgeBaseId": ""}),
        _node(
            "prompt",
            "prompt_llm",
            900,
            120,
            {"label": "Prompt / LLM", "prompt": "问题：{question}\n\n上下文：\n{contexts}\n\n请只基于上下文回答。"},
        ),
        _node("answer", "answer", 1080, 120, {"label": "Answer", "outputKey": "answer"}),
    ],
    "edges": [
        _edge("source", "parse"),
        _edge("parse", "chunk"),
        _edge("chunk", "embed"),
        _edge("embed", "retrieve"),
        _edge("retrieve", "prompt"),
        _edge("prompt", "answer"),
    ],
}


WORKFLOW_TEMPLATES: Dict[str, Dict[str, Any]] = {
    OFFLINE_DB_TEMPLATE_ID: {
        "id": OFFLINE_DB_TEMPLATE_ID,
        "name": "创建离线数据库",
        "description": "选择已有 Source DB，重新 Parse / Chunk / Embed / Index。",
        "node_types": ["source", "parse", "chunk", "embed_index"],
        "action": "prepare",
        "graph": {
            "templateId": OFFLINE_DB_TEMPLATE_ID,
            "nodes": [
                _node("source", "source", 0, 120, {"label": "Source DB", "knowledgeBaseId": ""}),
                _node("parse", "parse", 210, 120, {"label": "Parse", "parser": "auto"}),
                _node("chunk", "chunk", 420, 120, {"label": "Chunk", "chunkSize": 900, "chunkOverlap": 120}),
                _node("embed", "embed_index", 630, 120, {"label": "Embed / Index", "overwrite": True}),
            ],
            "edges": [_edge("source", "parse"), _edge("parse", "chunk"), _edge("chunk", "embed")],
        },
    },
    RAG_TEMPLATE_ID: {
        "id": RAG_TEMPLATE_ID,
        "name": "进行 RAG",
        "description": "选择已索引 DB，执行 Retrieve -> Prompt / LLM -> Answer。",
        "node_types": ["retrieve", "prompt_llm", "answer"],
        "action": "run",
        "graph": {
            "templateId": RAG_TEMPLATE_ID,
            "nodes": [
                _node("retrieve", "retrieve", 0, 120, {"label": "Retrieve", "topK": 3, "searchType": "similarity", "knowledgeBaseId": ""}),
                _node(
                    "prompt",
                    "prompt_llm",
                    240,
                    120,
                    {
                        "label": "Prompt / LLM",
                        "model": "",
                        "temperature": 0.2,
                        "prompt": "问题：{question}\n\n上下文：\n{contexts}\n\n请只基于上下文回答。",
                    },
                ),
                _node("answer", "answer", 480, 120, {"label": "Answer", "outputKey": "answer", "includeContexts": True}),
            ],
            "edges": [_edge("retrieve", "prompt"), _edge("prompt", "answer")],
        },
    },
    EVALUATION_TEMPLATE_ID: {
        "id": EVALUATION_TEMPLATE_ID,
        "name": "评测",
        "description": "生成 Query Set，执行 RAG，再运行 reference-free RAGAS。",
        "node_types": ["query_generate", "retrieve", "prompt_llm", "answer", "ragas_eval"],
        "action": "evaluate",
        "graph": {
            "templateId": EVALUATION_TEMPLATE_ID,
            "nodes": [
                _node(
                    "query_generate",
                    "query_generate",
                    0,
                    120,
                    {
                        "label": "Query Generate",
                        "knowledgeBaseId": "",
                        "name": "Workflow 生成的 Query 集",
                        "examples": ["如何配置这个产品？", "上传文档后怎么检索？", "评测结果怎么看？"],
                        "targetCount": 10,
                    },
                ),
                _node("retrieve", "retrieve", 240, 120, {"label": "Retrieve", "topK": 3, "searchType": "similarity", "knowledgeBaseId": ""}),
                _node(
                    "prompt",
                    "prompt_llm",
                    480,
                    120,
                    {
                        "label": "Prompt / LLM",
                        "model": "",
                        "temperature": 0.2,
                        "prompt": "问题：{question}\n\n上下文：\n{contexts}\n\n请只基于上下文回答。",
                    },
                ),
                _node("answer", "answer", 720, 120, {"label": "Answer", "outputKey": "answer", "includeContexts": True}),
                _node("ragas_eval", "ragas_eval", 960, 120, {"label": "RAGAS Eval", "metricPreset": "reference_free", "limit": ""}),
            ],
            "edges": [
                _edge("query_generate", "retrieve"),
                _edge("retrieve", "prompt"),
                _edge("prompt", "answer"),
                _edge("answer", "ragas_eval"),
            ],
        },
    },
}

SUPPORTED_NODE_TYPES = set(LEGACY_FULL_RAG_NODE_TYPES)
for template in WORKFLOW_TEMPLATES.values():
    SUPPORTED_NODE_TYPES.update(template["node_types"])


class WorkflowValidationError(ValueError):
    pass


def get_workflow_templates() -> List[Dict[str, Any]]:
    templates = []
    for template in WORKFLOW_TEMPLATES.values():
        item = {key: value for key, value in template.items() if key != "graph"}
        item["graph"] = deepcopy(template["graph"])
        templates.append(item)
    return templates


def get_default_workflow_graph(template_id: str = DEFAULT_TEMPLATE_ID) -> Dict[str, Any]:
    if template_id not in WORKFLOW_TEMPLATES:
        raise WorkflowValidationError(f"unsupported workflow template: {template_id}")
    return deepcopy(WORKFLOW_TEMPLATES[template_id]["graph"])


@dataclass
class WorkflowValidationResult:
    node_ids_by_type: Dict[str, str]
    nodes_by_type: Dict[str, Dict[str, Any]]
    template_id: str


RetrieverFn = Callable[[str], Iterable[Any]]
GeneratorFn = Callable[[str, List[str]], str]


class WorkflowEngine:
    def infer_template_id(self, graph: Dict[str, Any]) -> str:
        template_id = graph.get("templateId") or graph.get("template_id")
        if template_id:
            if template_id == LEGACY_FULL_RAG_TEMPLATE_ID:
                return LEGACY_FULL_RAG_TEMPLATE_ID
            if template_id not in WORKFLOW_TEMPLATES:
                raise WorkflowValidationError(f"unsupported workflow template: {template_id}")
            return str(template_id)

        node_types = [node.get("type") for node in graph.get("nodes") or []]
        if node_types == LEGACY_FULL_RAG_NODE_TYPES or set(node_types) == set(LEGACY_FULL_RAG_NODE_TYPES):
            return LEGACY_FULL_RAG_TEMPLATE_ID
        for candidate_id, template in WORKFLOW_TEMPLATES.items():
            if set(node_types) == set(template["node_types"]):
                return candidate_id
        return DEFAULT_TEMPLATE_ID

    def validate_graph(self, graph: Dict[str, Any]) -> WorkflowValidationResult:
        nodes = graph.get("nodes")
        edges = graph.get("edges")
        if not isinstance(nodes, list) or not isinstance(edges, list):
            raise WorkflowValidationError("workflow graph must contain nodes and edges lists")

        template_id = self.infer_template_id(graph)
        required_node_types = self._required_node_types(template_id)
        allowed_node_types = set(required_node_types)

        node_ids_by_type: Dict[str, str] = {}
        nodes_by_type: Dict[str, Dict[str, Any]] = {}
        for node in nodes:
            node_id = node.get("id")
            node_type = node.get("type")
            if not node_id or not node_type:
                raise WorkflowValidationError("each node must contain id and type")
            if node_type not in SUPPORTED_NODE_TYPES:
                raise WorkflowValidationError(f"unsupported node type: {node_type}")
            if node_type not in allowed_node_types:
                raise WorkflowValidationError(f"node type {node_type} is not allowed in template {template_id}")
            if node_type in node_ids_by_type:
                raise WorkflowValidationError(f"duplicate node type is not supported in v1: {node_type}")
            node_ids_by_type[node_type] = node_id
            nodes_by_type[node_type] = node

        missing = [node_type for node_type in required_node_types if node_type not in node_ids_by_type]
        if missing:
            raise WorkflowValidationError(f"workflow is missing required nodes: {', '.join(missing)}")

        allowed_pairs = {
            (node_ids_by_type[left], node_ids_by_type[right])
            for left, right in zip(required_node_types, required_node_types[1:])
        }
        edge_pairs = []
        for edge_item in edges:
            source = edge_item.get("source")
            target = edge_item.get("target")
            if source not in node_ids_by_type.values() or target not in node_ids_by_type.values():
                raise WorkflowValidationError("workflow edge references an unknown node")
            edge_pairs.append((source, target))

        edge_pair_set = set(edge_pairs)
        for pair in allowed_pairs:
            if pair not in edge_pair_set:
                left = next(key for key, value in node_ids_by_type.items() if value == pair[0])
                right = next(key for key, value in node_ids_by_type.items() if value == pair[1])
                raise WorkflowValidationError(f"workflow must connect {left} -> {right}")
        if edge_pair_set != allowed_pairs or len(edge_pairs) != len(allowed_pairs):
            chain = self._chain_label(required_node_types)
            raise WorkflowValidationError(f"workflow must use exactly the canonical {chain} DAG")

        validation = WorkflowValidationResult(
            node_ids_by_type=node_ids_by_type,
            nodes_by_type=nodes_by_type,
            template_id=template_id,
        )
        self._validate_node_configs(validation)
        return validation

    def is_prepare_graph(self, graph: Dict[str, Any]) -> bool:
        return self.validate_graph(graph).template_id in {OFFLINE_DB_TEMPLATE_ID, LEGACY_FULL_RAG_TEMPLATE_ID}

    def is_runtime_graph(self, graph: Dict[str, Any]) -> bool:
        return self.validate_graph(graph).template_id in {RAG_TEMPLATE_ID, LEGACY_FULL_RAG_TEMPLATE_ID}

    def is_evaluation_graph(self, graph: Dict[str, Any]) -> bool:
        return self.validate_graph(graph).template_id == EVALUATION_TEMPLATE_ID

    def get_source_knowledge_base_id_from_validation(
        self,
        validation: WorkflowValidationResult,
    ) -> int:
        source = validation.nodes_by_type.get("source")
        if source is None:
            raise WorkflowValidationError("Source DB node is required")
        source_data = source.get("data") or {}
        return self._read_int(
            source_data,
            "knowledgeBaseId",
            "knowledge_base_id",
            error_prefix="source.knowledgeBaseId",
            required_message="Source DB node must select a knowledge DB",
        )

    def get_source_knowledge_base_id(self, graph: Dict[str, Any]) -> int:
        validation = self.validate_graph(graph)
        return self.get_source_knowledge_base_id_from_validation(validation)

    def get_retrieve_knowledge_base_id(self, graph: Dict[str, Any]) -> Optional[int]:
        validation = self.validate_graph(graph)
        return self.get_retrieve_knowledge_base_id_from_validation(validation, required=False)

    def get_retrieve_knowledge_base_id_from_validation(
        self,
        validation: WorkflowValidationResult,
        *,
        required: bool = False,
    ) -> Optional[int]:
        retrieve = validation.nodes_by_type.get("retrieve")
        if retrieve is None:
            if required:
                raise WorkflowValidationError("Retrieve node is required")
            return None
        retrieve_data = retrieve.get("data") or {}
        kb_id = retrieve_data.get("knowledgeBaseId") or retrieve_data.get("knowledge_base_id")
        if kb_id in (None, ""):
            if required:
                raise WorkflowValidationError("Retrieve node must select a knowledge DB")
            return None
        try:
            return int(kb_id)
        except (TypeError, ValueError):
            raise WorkflowValidationError("retrieve.knowledgeBaseId must be an integer")

    def get_query_generate_config(
        self,
        graph: Dict[str, Any],
        *,
        node_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        validation = self.validate_graph(graph)
        return self.get_query_generate_config_from_validation(validation, node_id=node_id)

    def get_query_generate_config_from_validation(
        self,
        validation: WorkflowValidationResult,
        *,
        node_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        query_node = validation.nodes_by_type.get("query_generate")
        if query_node is None:
            raise WorkflowValidationError("Query Generate node is required")
        if node_id is not None and query_node.get("id") != node_id:
            raise WorkflowValidationError("only Query Generate node can be run directly")
        data = query_node.get("data") or {}
        knowledge_base_id = self._read_int(
            data,
            "knowledgeBaseId",
            "knowledge_base_id",
            error_prefix="query_generate.knowledgeBaseId",
            required_message="Query Generate node must select a knowledge DB",
        )
        examples = self._read_examples(data)
        try:
            target_count = int(data.get("targetCount") or data.get("target_count") or 10)
        except (TypeError, ValueError):
            raise WorkflowValidationError("query_generate.targetCount must be an integer")
        if target_count <= 0 or target_count > 500:
            raise WorkflowValidationError("query_generate.targetCount must be between 1 and 500")
        name = str(data.get("name") or data.get("querySetName") or "Workflow 生成的 Query 集").strip()
        if not name:
            raise WorkflowValidationError("query_generate.name is required")
        return {
            "knowledge_base_id": knowledge_base_id,
            "examples": examples,
            "target_count": target_count,
            "name": name,
        }

    def get_eval_config(self, graph: Dict[str, Any]) -> Dict[str, Any]:
        validation = self.validate_graph(graph)
        return self.get_eval_config_from_validation(validation)

    def resolve_knowledge_base_id(self, graph: Dict[str, Any]) -> int:
        validation = self.validate_graph(graph)
        retrieve_kb_id = self.get_retrieve_knowledge_base_id_from_validation(validation, required=False)
        if retrieve_kb_id is not None:
            return retrieve_kb_id
        if "source" in validation.nodes_by_type:
            return self.get_source_knowledge_base_id_from_validation(validation)
        if "query_generate" in validation.nodes_by_type:
            return self.get_query_generate_config_from_validation(validation)["knowledge_base_id"]
        raise WorkflowValidationError("workflow must select a knowledge DB")

    def get_chunk_config(self, graph: Dict[str, Any]) -> Dict[str, int]:
        validation = self.validate_graph(graph)
        return self.get_chunk_config_from_validation(validation)

    def get_top_k(self, graph: Dict[str, Any], default: int = 3) -> int:
        validation = self.validate_graph(graph)
        return self.get_top_k_from_validation(validation, default=default)

    def get_top_k_from_validation(self, validation: WorkflowValidationResult, default: int = 3) -> int:
        retrieve_data = validation.nodes_by_type["retrieve"].get("data") or {}
        graph_k = retrieve_data.get("topK") or retrieve_data.get("k") or default
        try:
            k = int(graph_k)
        except (TypeError, ValueError):
            raise WorkflowValidationError("retrieve.topK must be an integer")
        if k <= 0:
            raise WorkflowValidationError("retrieve.topK must be positive")
        return k

    def run_question(
        self,
        graph: Dict[str, Any],
        *,
        question: str,
        vector_manager: Optional[Any] = None,
        collection_name: Optional[str] = None,
        config_path: str = "config/application.yaml",
        retriever: Optional[RetrieverFn] = None,
        generator: Optional[GeneratorFn] = None,
        k: int = 3,
    ) -> Dict[str, Any]:
        validation = self.validate_graph(graph)
        retrieve_data = validation.nodes_by_type["retrieve"].get("data") or {}
        prompt_data = validation.nodes_by_type["prompt_llm"].get("data") or {}
        graph_k = retrieve_data.get("topK") or retrieve_data.get("k")
        if graph_k is not None:
            try:
                k = int(graph_k)
            except (TypeError, ValueError):
                raise WorkflowValidationError("retrieve.topK must be an integer")
        prompt_text = prompt_data.get("prompt") or None

        if retriever is not None:
            raw_docs = list(retriever(question))
            contexts = self._normalize_contexts(raw_docs)
            if generator is None:
                answer = "\n".join(contexts)
            else:
                answer = generator(question, contexts)
            return {"question": question, "answer": answer, "contexts": contexts}

        if vector_manager is None:
            raise ValueError("vector_manager is required when retriever is not provided")
        if not collection_name:
            raise ValueError("collection_name is required when using vector_manager")

        retriever_obj = vector_manager.get_retriever(collection_name, k=k)
        runner = NormalRag(
            retriever=retriever_obj,
            config_path=config_path,
            prompt_text=prompt_text,
        )
        return runner.invoke(question)

    def _required_node_types(self, template_id: str) -> List[str]:
        if template_id == LEGACY_FULL_RAG_TEMPLATE_ID:
            return LEGACY_FULL_RAG_NODE_TYPES
        return list(WORKFLOW_TEMPLATES[template_id]["node_types"])

    @staticmethod
    def _chain_label(node_types: List[str]) -> str:
        labels = {
            "source": "Source",
            "parse": "Parse",
            "chunk": "Chunk",
            "embed_index": "Embed",
            "query_generate": "Query Generate",
            "retrieve": "Retrieve",
            "prompt_llm": "Prompt",
            "answer": "Answer",
            "ragas_eval": "RAGAS Eval",
        }
        return " -> ".join(labels.get(node_type, node_type) for node_type in node_types)

    def _validate_node_configs(self, validation: WorkflowValidationResult) -> None:
        if validation.template_id in {OFFLINE_DB_TEMPLATE_ID, LEGACY_FULL_RAG_TEMPLATE_ID}:
            self.get_source_knowledge_base_id_from_validation(validation)
            if "chunk" in validation.nodes_by_type:
                self.get_chunk_config_from_validation(validation)
        if validation.template_id == RAG_TEMPLATE_ID:
            self.get_retrieve_knowledge_base_id_from_validation(validation, required=True)
            self.get_top_k_from_validation(validation)
        if validation.template_id == EVALUATION_TEMPLATE_ID:
            self.get_query_generate_config_from_validation(validation)
            self.get_retrieve_knowledge_base_id_from_validation(validation, required=False)
            self.get_top_k_from_validation(validation)
            self.get_eval_config_from_validation(validation)

    def get_chunk_config_from_validation(self, validation: WorkflowValidationResult) -> Dict[str, int]:
        chunk_node = validation.nodes_by_type.get("chunk")
        if chunk_node is None:
            raise WorkflowValidationError("Chunk node is required")
        chunk_data = chunk_node.get("data") or {}
        try:
            chunk_size = int(chunk_data.get("chunkSize") or chunk_data.get("chunk_size") or 900)
            chunk_overlap = int(chunk_data.get("chunkOverlap") or chunk_data.get("chunk_overlap") or 120)
        except (TypeError, ValueError):
            raise WorkflowValidationError("chunk size and overlap must be integers")
        if chunk_size <= 0:
            raise WorkflowValidationError("chunk.chunkSize must be positive")
        if chunk_overlap < 0 or chunk_overlap >= chunk_size:
            raise WorkflowValidationError("chunk.chunkOverlap must be >= 0 and smaller than chunkSize")
        return {"chunk_size": chunk_size, "chunk_overlap": chunk_overlap}

    def get_eval_config_from_validation(self, validation: WorkflowValidationResult) -> Dict[str, Any]:
        eval_node = validation.nodes_by_type.get("ragas_eval")
        if eval_node is None:
            raise WorkflowValidationError("RAGAS Eval node is required")
        data = eval_node.get("data") or {}
        metric_preset = data.get("metricPreset") or data.get("metric_preset") or "reference_free"
        if metric_preset != "reference_free":
            raise WorkflowValidationError("ragas_eval.metricPreset only supports reference_free in v1")
        raw_limit = data.get("limit")
        limit = None
        if raw_limit not in (None, ""):
            try:
                limit = int(raw_limit)
            except (TypeError, ValueError):
                raise WorkflowValidationError("ragas_eval.limit must be an integer")
            if limit <= 0:
                raise WorkflowValidationError("ragas_eval.limit must be positive")
        return {"metric_preset": metric_preset, "limit": limit}

    @staticmethod
    def _read_int(
        data: Dict[str, Any],
        *keys: str,
        error_prefix: str,
        required_message: str,
    ) -> int:
        value = None
        for key in keys:
            value = data.get(key)
            if value not in (None, ""):
                break
        if value in (None, ""):
            raise WorkflowValidationError(required_message)
        try:
            return int(value)
        except (TypeError, ValueError):
            raise WorkflowValidationError(f"{error_prefix} must be an integer")

    @staticmethod
    def _read_examples(data: Dict[str, Any]) -> List[str]:
        raw_examples = data.get("examples")
        if isinstance(raw_examples, list):
            examples = [str(item).strip() for item in raw_examples if str(item).strip()]
        else:
            text = str(data.get("examplesText") or raw_examples or "")
            examples = [line.strip() for line in text.splitlines() if line.strip()]
        if len(examples) < 3 or len(examples) > 5:
            raise WorkflowValidationError("query_generate.examples requires 3 to 5 example queries")
        return examples

    @staticmethod
    def _normalize_contexts(items: Iterable[Any]) -> List[str]:
        contexts: List[str] = []
        for item in items:
            if isinstance(item, str):
                contexts.append(item)
                continue
            if isinstance(item, dict):
                if "content" in item:
                    contexts.append(str(item["content"]))
                    continue
                if "page_content" in item:
                    contexts.append(str(item["page_content"]))
                    continue
            page_content = getattr(item, "page_content", None)
            if page_content is not None:
                contexts.append(str(page_content))
                continue
            contexts.append(str(item))
        return contexts
