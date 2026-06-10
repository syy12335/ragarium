from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Callable, Dict, Iterable, List, Optional

from rag_eval.rag.normal_rag import NormalRag


BLANK_TEMPLATE_ID = "blank"
OFFLINE_DB_TEMPLATE_ID = "offline_db"
RAG_TEMPLATE_ID = "rag"
EVALUATION_TEMPLATE_ID = "evaluation"
LEGACY_FULL_RAG_TEMPLATE_ID = "legacy_full_rag"
DEFAULT_TEMPLATE_ID = BLANK_TEMPLATE_ID

START_NODE_TYPE = "start"
END_NODE_TYPE = "end"

LEGACY_FULL_RAG_NODE_TYPES = [
    "source",
    "parse",
    "chunk",
    "embed_index",
    "retrieve",
    "prompt_llm",
    "answer",
]

EXECUTABLE_NODE_TYPES = {
    START_NODE_TYPE,
    "source",
    "parse",
    "chunk",
    "embed_index",
    "query_generate",
    "retrieve",
    "prompt_llm",
    "answer",
    "ragas_eval",
    END_NODE_TYPE,
}


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


def _start_node(x: int = 0, y: int = 120, fields: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    return _node(
        "start",
        START_NODE_TYPE,
        x,
        y,
        {
            "label": "Start",
            "fields": fields or [],
        },
    )


def _end_node(x: int = 720, y: int = 120) -> Dict[str, Any]:
    return _node(
        "end",
        END_NODE_TYPE,
        x,
        y,
        {
            "label": "End",
            "outputs": [],
        },
    )


WORKFLOW_TEMPLATES: Dict[str, Dict[str, Any]] = {
    BLANK_TEMPLATE_ID: {
        "id": BLANK_TEMPLATE_ID,
        "name": "空白",
        "description": "只包含 Start 和 End，适合从零搭建自定义 graph。",
        "node_types": [START_NODE_TYPE, END_NODE_TYPE],
        "action": "draft",
        "graph": {
            "templateId": BLANK_TEMPLATE_ID,
            "nodes": [_start_node(0, 120), _end_node(360, 120)],
            "edges": [],
        },
    },
    OFFLINE_DB_TEMPLATE_ID: {
        "id": OFFLINE_DB_TEMPLATE_ID,
        "name": "创建离线数据库",
        "description": "选择已有 Source DB，重新 Parse / Chunk / Embed / Index。",
        "node_types": [START_NODE_TYPE, "source", "parse", "chunk", "embed_index", END_NODE_TYPE],
        "action": "prepare",
        "graph": {
            "templateId": OFFLINE_DB_TEMPLATE_ID,
            "nodes": [
                _start_node(0, 120),
                _node("source", "source", 210, 120, {"label": "Source DB", "knowledgeBaseId": ""}),
                _node("parse", "parse", 420, 120, {"label": "Parse", "parser": "auto"}),
                _node("chunk", "chunk", 630, 120, {"label": "Chunk", "chunkSize": 900, "chunkOverlap": 120}),
                _node("embed", "embed_index", 840, 120, {"label": "Embed / Index", "overwrite": True}),
                _end_node(1050, 120),
            ],
            "edges": [
                _edge("start", "source"),
                _edge("source", "parse"),
                _edge("parse", "chunk"),
                _edge("chunk", "embed"),
                _edge("embed", "end"),
            ],
        },
    },
    RAG_TEMPLATE_ID: {
        "id": RAG_TEMPLATE_ID,
        "name": "进行 RAG",
        "description": "选择已索引 DB，执行 Retrieve -> Prompt / LLM -> Answer。",
        "node_types": [START_NODE_TYPE, "retrieve", "prompt_llm", "answer", END_NODE_TYPE],
        "action": "run",
        "graph": {
            "templateId": RAG_TEMPLATE_ID,
            "nodes": [
                _start_node(
                    0,
                    120,
                    [{"name": "question", "type": "string", "required": True, "default": ""}],
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
                _end_node(960, 120),
            ],
            "edges": [
                _edge("start", "retrieve"),
                _edge("retrieve", "prompt"),
                _edge("prompt", "answer"),
                _edge("answer", "end"),
            ],
        },
    },
    EVALUATION_TEMPLATE_ID: {
        "id": EVALUATION_TEMPLATE_ID,
        "name": "评测",
        "description": "生成 Query Set，执行 RAG，再运行 reference-free RAGAS。",
        "node_types": [START_NODE_TYPE, "query_generate", "retrieve", "prompt_llm", "answer", "ragas_eval", END_NODE_TYPE],
        "action": "evaluate",
        "graph": {
            "templateId": EVALUATION_TEMPLATE_ID,
            "nodes": [
                _start_node(0, 120),
                _node(
                    "query_generate",
                    "query_generate",
                    240,
                    120,
                    {
                        "label": "Query Generate",
                        "knowledgeBaseId": "",
                        "name": "Workflow 生成的 Query 集",
                        "examples": ["如何配置这个产品？", "上传文档后怎么检索？", "评测结果怎么看？"],
                        "targetCount": 10,
                    },
                ),
                _node("retrieve", "retrieve", 480, 120, {"label": "Retrieve", "topK": 3, "searchType": "similarity", "knowledgeBaseId": ""}),
                _node(
                    "prompt",
                    "prompt_llm",
                    720,
                    120,
                    {
                        "label": "Prompt / LLM",
                        "model": "",
                        "temperature": 0.2,
                        "prompt": "问题：{question}\n\n上下文：\n{contexts}\n\n请只基于上下文回答。",
                    },
                ),
                _node("answer", "answer", 960, 120, {"label": "Answer", "outputKey": "answer", "includeContexts": True}),
                _node("ragas_eval", "ragas_eval", 1200, 120, {"label": "RAGAS Eval", "metricPreset": "reference_free", "limit": ""}),
                _end_node(1440, 120),
            ],
            "edges": [
                _edge("start", "query_generate"),
                _edge("query_generate", "retrieve"),
                _edge("retrieve", "prompt"),
                _edge("prompt", "answer"),
                _edge("answer", "ragas_eval"),
                _edge("ragas_eval", "end"),
            ],
        },
    },
}


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
    nodes_by_id: Dict[str, Dict[str, Any]]
    ordered_nodes: List[Dict[str, Any]]
    template_id: str
    is_legacy: bool = False


RetrieverFn = Callable[[str], Iterable[Any]]
GeneratorFn = Callable[[str, List[str]], str]


class WorkflowEngine:
    def infer_template_id(self, graph: Dict[str, Any]) -> str:
        template_id = graph.get("templateId") or graph.get("template_id")
        if template_id and template_id in WORKFLOW_TEMPLATES:
            return str(template_id)
        if template_id == LEGACY_FULL_RAG_TEMPLATE_ID:
            return LEGACY_FULL_RAG_TEMPLATE_ID

        node_types = [node.get("type") for node in graph.get("nodes") or []]
        if self._is_legacy_full_rag_types(node_types):
            return LEGACY_FULL_RAG_TEMPLATE_ID
        for candidate_id, template in WORKFLOW_TEMPLATES.items():
            if set(node_types) == set(template["node_types"]):
                return candidate_id
        return str(template_id or "custom")

    def validate_graph_structure(self, graph: Dict[str, Any]) -> WorkflowValidationResult:
        nodes = graph.get("nodes")
        edges = graph.get("edges")
        if not isinstance(nodes, list) or not isinstance(edges, list):
            raise WorkflowValidationError("workflow graph must contain nodes and edges lists")

        node_ids_by_type: Dict[str, str] = {}
        nodes_by_type: Dict[str, Dict[str, Any]] = {}
        nodes_by_id: Dict[str, Dict[str, Any]] = {}
        for node in nodes:
            node_id = node.get("id")
            node_type = node.get("type")
            if not node_id or not node_type:
                raise WorkflowValidationError("each node must contain id and type")
            if node_type not in EXECUTABLE_NODE_TYPES:
                raise WorkflowValidationError(f"unsupported node type: {node_type}")
            if node_id in nodes_by_id:
                raise WorkflowValidationError(f"duplicate node id is not supported: {node_id}")
            nodes_by_id[node_id] = node
            node_ids_by_type.setdefault(node_type, node_id)
            nodes_by_type.setdefault(node_type, node)

        for edge_item in edges:
            source = edge_item.get("source")
            target = edge_item.get("target")
            if source not in nodes_by_id or target not in nodes_by_id:
                raise WorkflowValidationError("workflow edge references an unknown node")

        node_types = [node.get("type") for node in nodes]
        return WorkflowValidationResult(
            node_ids_by_type=node_ids_by_type,
            nodes_by_type=nodes_by_type,
            nodes_by_id=nodes_by_id,
            ordered_nodes=list(nodes),
            template_id=self.infer_template_id(graph),
            is_legacy=self._is_legacy_full_rag_types(node_types) and START_NODE_TYPE not in node_types and END_NODE_TYPE not in node_types,
        )

    def validate_graph(self, graph: Dict[str, Any]) -> WorkflowValidationResult:
        return self.validate_executable_graph(graph)

    def validate_executable_graph(self, graph: Dict[str, Any]) -> WorkflowValidationResult:
        validation = self.validate_graph_structure(graph)
        if validation.is_legacy:
            self._validate_legacy_full_rag(graph, validation)
            return validation

        start_nodes = [node for node in validation.ordered_nodes if node.get("type") == START_NODE_TYPE]
        end_nodes = [node for node in validation.ordered_nodes if node.get("type") == END_NODE_TYPE]
        if len(start_nodes) != 1:
            raise WorkflowValidationError("workflow must contain exactly one Start node")
        if len(end_nodes) != 1:
            raise WorkflowValidationError("workflow must contain exactly one End node")

        business_nodes = [
            node for node in validation.ordered_nodes
            if node.get("type") not in {START_NODE_TYPE, END_NODE_TYPE}
        ]
        if not business_nodes:
            raise WorkflowValidationError("workflow must contain at least one executable node between Start and End")

        ordered_ids = self.topological_order(graph, validation)
        start_id = start_nodes[0]["id"]
        end_id = end_nodes[0]["id"]
        reachable_from_start = self._reachable_from(graph, start_id)
        can_reach_end = self._can_reach(graph, end_id)
        for node_id in validation.nodes_by_id:
            if node_id not in reachable_from_start:
                raise WorkflowValidationError(f"workflow node is not reachable from Start: {node_id}")
            if node_id not in can_reach_end:
                raise WorkflowValidationError(f"workflow node cannot reach End: {node_id}")
        if ordered_ids[0] != start_id:
            raise WorkflowValidationError("Start node must be the first executable node")
        if ordered_ids[-1] != end_id:
            raise WorkflowValidationError("End node must be the last executable node")

        self._validate_node_configs(validation)
        return WorkflowValidationResult(
            node_ids_by_type=validation.node_ids_by_type,
            nodes_by_type=validation.nodes_by_type,
            nodes_by_id=validation.nodes_by_id,
            ordered_nodes=[validation.nodes_by_id[node_id] for node_id in ordered_ids],
            template_id=validation.template_id,
            is_legacy=False,
        )

    def topological_order(
        self,
        graph: Dict[str, Any],
        validation: Optional[WorkflowValidationResult] = None,
    ) -> List[str]:
        validation = validation or self.validate_graph_structure(graph)
        incoming = {node_id: 0 for node_id in validation.nodes_by_id}
        outgoing = {node_id: [] for node_id in validation.nodes_by_id}
        for edge_item in graph.get("edges") or []:
            source = edge_item["source"]
            target = edge_item["target"]
            outgoing[source].append(target)
            incoming[target] += 1

        queue = [node_id for node_id, count in incoming.items() if count == 0]
        ordered: List[str] = []
        while queue:
            node_id = queue.pop(0)
            ordered.append(node_id)
            for target in outgoing[node_id]:
                incoming[target] -= 1
                if incoming[target] == 0:
                    queue.append(target)
        if len(ordered) != len(validation.nodes_by_id):
            raise WorkflowValidationError("workflow graph must be a DAG")
        return ordered

    def is_prepare_graph(self, graph: Dict[str, Any]) -> bool:
        validation = self.validate_executable_graph(graph)
        types = {node.get("type") for node in validation.ordered_nodes}
        return validation.is_legacy or {"source", "chunk", "embed_index"}.issubset(types)

    def is_runtime_graph(self, graph: Dict[str, Any]) -> bool:
        validation = self.validate_executable_graph(graph)
        types = {node.get("type") for node in validation.ordered_nodes}
        if validation.is_legacy:
            return True
        start_fields = self.get_start_fields(graph)
        has_question_input = any(field["name"] == "question" for field in start_fields)
        return (
            {"retrieve", "prompt_llm", "answer"}.issubset(types)
            and "query_generate" not in types
            and "ragas_eval" not in types
            and has_question_input
        )

    def is_evaluation_graph(self, graph: Dict[str, Any]) -> bool:
        validation = self.validate_executable_graph(graph)
        types = {node.get("type") for node in validation.ordered_nodes}
        return {"query_generate", "ragas_eval"}.issubset(types)

    def get_start_fields(self, graph: Dict[str, Any]) -> List[Dict[str, Any]]:
        validation = self.validate_graph_structure(graph)
        start = validation.nodes_by_type.get(START_NODE_TYPE)
        if not start:
            return []
        fields = start.get("data", {}).get("fields") or []
        if not isinstance(fields, list):
            raise WorkflowValidationError("start.fields must be a list")
        normalized = []
        for field in fields:
            if not isinstance(field, dict):
                raise WorkflowValidationError("each start field must be an object")
            name = str(field.get("name") or "").strip()
            if not name:
                raise WorkflowValidationError("start field name is required")
            field_type = field.get("type") or "string"
            if field_type not in {"string", "number", "boolean", "json"}:
                raise WorkflowValidationError(f"unsupported start field type: {field_type}")
            normalized.append(
                {
                    "name": name,
                    "type": field_type,
                    "required": bool(field.get("required")),
                    "default": field.get("default"),
                }
            )
        return normalized

    def resolve_start_inputs(self, graph: Dict[str, Any], inputs: Dict[str, Any]) -> Dict[str, Any]:
        resolved: Dict[str, Any] = {}
        for field in self.get_start_fields(graph):
            name = field["name"]
            value = inputs.get(name, field.get("default"))
            if field["required"] and value in (None, ""):
                raise WorkflowValidationError(f"start input is required: {name}")
            if value in (None, ""):
                continue
            resolved[name] = self._coerce_start_value(value, field["type"], name)
        for key, value in inputs.items():
            if key not in resolved and value not in (None, ""):
                resolved[key] = value
        return resolved

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
        validation = self.validate_graph_structure(graph)
        return self.get_source_knowledge_base_id_from_validation(validation)

    def get_retrieve_knowledge_base_id(self, graph: Dict[str, Any]) -> Optional[int]:
        validation = self.validate_graph_structure(graph)
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
        validation = self.validate_graph_structure(graph)
        return self.get_query_generate_config_from_validation(validation, node_id=node_id)

    def get_query_generate_config_from_validation(
        self,
        validation: WorkflowValidationResult,
        *,
        node_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        query_node = self._node_for_type(validation, "query_generate", node_id=node_id)
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
        validation = self.validate_graph_structure(graph)
        return self.get_eval_config_from_validation(validation)

    def resolve_knowledge_base_id(self, graph: Dict[str, Any]) -> int:
        validation = self.validate_graph_structure(graph)
        retrieve_kb_id = self.get_retrieve_knowledge_base_id_from_validation(validation, required=False)
        if retrieve_kb_id is not None:
            return retrieve_kb_id
        if "source" in validation.nodes_by_type:
            return self.get_source_knowledge_base_id_from_validation(validation)
        if "query_generate" in validation.nodes_by_type:
            return self.get_query_generate_config_from_validation(validation)["knowledge_base_id"]
        raise WorkflowValidationError("workflow must select a knowledge DB")

    def get_chunk_config(self, graph: Dict[str, Any]) -> Dict[str, int]:
        validation = self.validate_graph_structure(graph)
        return self.get_chunk_config_from_validation(validation)

    def get_top_k(self, graph: Dict[str, Any], default: int = 3) -> int:
        validation = self.validate_graph_structure(graph)
        return self.get_top_k_from_validation(validation, default=default)

    def get_top_k_from_validation(self, validation: WorkflowValidationResult, default: int = 3) -> int:
        retrieve = validation.nodes_by_type.get("retrieve")
        if retrieve is None:
            raise WorkflowValidationError("Retrieve node is required")
        retrieve_data = retrieve.get("data") or {}
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
        validation = self.validate_executable_graph(graph)
        if not {"retrieve", "prompt_llm", "answer"}.issubset({node.get("type") for node in validation.ordered_nodes}):
            raise WorkflowValidationError("workflow must contain Retrieve, Prompt / LLM and Answer nodes")
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

    def _validate_legacy_full_rag(self, graph: Dict[str, Any], validation: WorkflowValidationResult) -> None:
        node_types = [node.get("type") for node in validation.ordered_nodes]
        if set(node_types) != set(LEGACY_FULL_RAG_NODE_TYPES):
            raise WorkflowValidationError("legacy full RAG workflow has unsupported nodes")
        allowed_pairs = {
            (validation.node_ids_by_type[left], validation.node_ids_by_type[right])
            for left, right in zip(LEGACY_FULL_RAG_NODE_TYPES, LEGACY_FULL_RAG_NODE_TYPES[1:])
        }
        edge_pairs = [(edge["source"], edge["target"]) for edge in graph.get("edges") or []]
        edge_pair_set = set(edge_pairs)
        for pair in allowed_pairs:
            if pair not in edge_pair_set:
                left = next(key for key, value in validation.node_ids_by_type.items() if value == pair[0])
                right = next(key for key, value in validation.node_ids_by_type.items() if value == pair[1])
                raise WorkflowValidationError(f"workflow must connect {left} -> {right}")
        if edge_pair_set != allowed_pairs or len(edge_pairs) != len(allowed_pairs):
            raise WorkflowValidationError(f"workflow must use exactly the canonical {self._chain_label(LEGACY_FULL_RAG_NODE_TYPES)} DAG")
        self._validate_node_configs(validation)

    @staticmethod
    def _chain_label(node_types: List[str]) -> str:
        labels = {
            "start": "Start",
            "source": "Source",
            "parse": "Parse",
            "chunk": "Chunk",
            "embed_index": "Embed",
            "query_generate": "Query Generate",
            "retrieve": "Retrieve",
            "prompt_llm": "Prompt",
            "answer": "Answer",
            "ragas_eval": "RAGAS Eval",
            "end": "End",
        }
        return " -> ".join(labels.get(node_type, node_type) for node_type in node_types)

    def _validate_node_configs(self, validation: WorkflowValidationResult) -> None:
        if START_NODE_TYPE in validation.nodes_by_type:
            self.get_start_fields_from_validation(validation)
        if "source" in validation.nodes_by_type:
            self.get_source_knowledge_base_id_from_validation(validation)
        if "chunk" in validation.nodes_by_type:
            self.get_chunk_config_from_validation(validation)
        if "retrieve" in validation.nodes_by_type:
            has_upstream_db = "source" in validation.nodes_by_type or "query_generate" in validation.nodes_by_type
            self.get_retrieve_knowledge_base_id_from_validation(validation, required=not has_upstream_db)
            self.get_top_k_from_validation(validation)
        if "query_generate" in validation.nodes_by_type:
            self.get_query_generate_config_from_validation(validation)
        if "ragas_eval" in validation.nodes_by_type:
            if "answer" not in validation.nodes_by_type:
                raise WorkflowValidationError("RAGAS Eval node requires an upstream Answer node")
            self.get_eval_config_from_validation(validation)

    def get_start_fields_from_validation(self, validation: WorkflowValidationResult) -> List[Dict[str, Any]]:
        start = validation.nodes_by_type.get(START_NODE_TYPE)
        if start is None:
            raise WorkflowValidationError("Start node is required")
        return self.get_start_fields({"nodes": [start], "edges": []})

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

    def _reachable_from(self, graph: Dict[str, Any], start_id: str) -> set[str]:
        outgoing: Dict[str, List[str]] = {}
        for edge_item in graph.get("edges") or []:
            outgoing.setdefault(edge_item["source"], []).append(edge_item["target"])
        seen = {start_id}
        queue = [start_id]
        while queue:
            node_id = queue.pop(0)
            for target in outgoing.get(node_id, []):
                if target not in seen:
                    seen.add(target)
                    queue.append(target)
        return seen

    def _can_reach(self, graph: Dict[str, Any], end_id: str) -> set[str]:
        incoming: Dict[str, List[str]] = {}
        for edge_item in graph.get("edges") or []:
            incoming.setdefault(edge_item["target"], []).append(edge_item["source"])
        seen = {end_id}
        queue = [end_id]
        while queue:
            node_id = queue.pop(0)
            for source in incoming.get(node_id, []):
                if source not in seen:
                    seen.add(source)
                    queue.append(source)
        return seen

    @staticmethod
    def _node_for_type(
        validation: WorkflowValidationResult,
        node_type: str,
        *,
        node_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        if node_id is not None:
            node = validation.nodes_by_id.get(node_id)
            if not node or node.get("type") != node_type:
                raise WorkflowValidationError(f"node {node_id} is not a {node_type} node")
            return node
        node = validation.nodes_by_type.get(node_type)
        if node is None:
            raise WorkflowValidationError(f"{node_type} node is required")
        return node

    @staticmethod
    def _is_legacy_full_rag_types(node_types: List[Any]) -> bool:
        return set(node_types) == set(LEGACY_FULL_RAG_NODE_TYPES) and len(node_types) == len(LEGACY_FULL_RAG_NODE_TYPES)

    @staticmethod
    def _coerce_start_value(value: Any, field_type: str, name: str) -> Any:
        if field_type == "string":
            return str(value)
        if field_type == "number":
            try:
                return float(value)
            except (TypeError, ValueError):
                raise WorkflowValidationError(f"start input must be a number: {name}")
        if field_type == "boolean":
            if isinstance(value, bool):
                return value
            if str(value).lower() in {"true", "1", "yes", "on"}:
                return True
            if str(value).lower() in {"false", "0", "no", "off"}:
                return False
            raise WorkflowValidationError(f"start input must be a boolean: {name}")
        return value

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
