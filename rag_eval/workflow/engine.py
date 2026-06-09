from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, Iterable, List, Optional

from rag_eval.rag.normal_rag import NormalRag


CANONICAL_NODE_TYPES = [
    "source",
    "parse",
    "chunk",
    "embed_index",
    "retrieve",
    "prompt_llm",
    "answer",
]

DEFAULT_WORKFLOW_GRAPH: Dict[str, Any] = {
    "nodes": [
        {"id": "source", "type": "source", "position": {"x": 0, "y": 120}, "data": {"label": "Source DB", "knowledgeBaseId": ""}},
        {"id": "parse", "type": "parse", "position": {"x": 180, "y": 120}, "data": {"label": "Parse", "parser": "auto"}},
        {"id": "chunk", "type": "chunk", "position": {"x": 360, "y": 120}, "data": {"label": "Chunk", "chunkSize": 900, "chunkOverlap": 120}},
        {"id": "embed", "type": "embed_index", "position": {"x": 540, "y": 120}, "data": {"label": "Embed / Index", "collection": "selected_knowledge_base"}},
        {"id": "retrieve", "type": "retrieve", "position": {"x": 720, "y": 120}, "data": {"label": "Retrieve", "topK": 3, "knowledgeBaseId": ""}},
        {"id": "prompt", "type": "prompt_llm", "position": {"x": 900, "y": 120}, "data": {"label": "Prompt / LLM", "prompt": "问题：{question}\n\n上下文：\n{contexts}\n\n请只基于上下文回答。"}},
        {"id": "answer", "type": "answer", "position": {"x": 1080, "y": 120}, "data": {"label": "Answer", "outputKey": "answer"}},
    ],
    "edges": [
        {"id": "source-parse", "source": "source", "target": "parse"},
        {"id": "parse-chunk", "source": "parse", "target": "chunk"},
        {"id": "chunk-embed", "source": "chunk", "target": "embed"},
        {"id": "embed-retrieve", "source": "embed", "target": "retrieve"},
        {"id": "retrieve-prompt", "source": "retrieve", "target": "prompt"},
        {"id": "prompt-answer", "source": "prompt", "target": "answer"},
    ],
}


class WorkflowValidationError(ValueError):
    pass


@dataclass
class WorkflowValidationResult:
    node_ids_by_type: Dict[str, str]
    nodes_by_type: Dict[str, Dict[str, Any]]


RetrieverFn = Callable[[str], Iterable[Any]]
GeneratorFn = Callable[[str, List[str]], str]


class WorkflowEngine:
    def validate_graph(self, graph: Dict[str, Any]) -> WorkflowValidationResult:
        nodes = graph.get("nodes")
        edges = graph.get("edges")
        if not isinstance(nodes, list) or not isinstance(edges, list):
            raise WorkflowValidationError("workflow graph must contain nodes and edges lists")

        node_ids_by_type: Dict[str, str] = {}
        nodes_by_type: Dict[str, Dict[str, Any]] = {}
        for node in nodes:
            node_id = node.get("id")
            node_type = node.get("type")
            if not node_id or not node_type:
                raise WorkflowValidationError("each node must contain id and type")
            if node_type not in CANONICAL_NODE_TYPES:
                raise WorkflowValidationError(f"unsupported node type: {node_type}")
            if node_type in node_ids_by_type:
                raise WorkflowValidationError(f"duplicate node type is not supported in v1: {node_type}")
            node_ids_by_type[node_type] = node_id
            nodes_by_type[node_type] = node

        missing = [node_type for node_type in CANONICAL_NODE_TYPES if node_type not in node_ids_by_type]
        if missing:
            raise WorkflowValidationError(f"workflow is missing required nodes: {', '.join(missing)}")

        allowed_pairs = {
            (node_ids_by_type[left], node_ids_by_type[right])
            for left, right in zip(CANONICAL_NODE_TYPES, CANONICAL_NODE_TYPES[1:])
        }
        edge_pairs = []
        for edge in edges:
            source = edge.get("source")
            target = edge.get("target")
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
            raise WorkflowValidationError("workflow must use exactly the canonical Source -> Parse -> Chunk -> Embed -> Retrieve -> Prompt -> Answer DAG")

        self.get_source_knowledge_base_id_from_validation(
            WorkflowValidationResult(node_ids_by_type=node_ids_by_type, nodes_by_type=nodes_by_type)
        )

        return WorkflowValidationResult(node_ids_by_type=node_ids_by_type, nodes_by_type=nodes_by_type)

    def get_source_knowledge_base_id_from_validation(
        self,
        validation: WorkflowValidationResult,
    ) -> int:
        source_data = validation.nodes_by_type["source"].get("data") or {}
        kb_id = source_data.get("knowledgeBaseId") or source_data.get("knowledge_base_id")
        if kb_id in (None, ""):
            raise WorkflowValidationError("Source DB node must select a knowledge DB")
        try:
            return int(kb_id)
        except (TypeError, ValueError):
            raise WorkflowValidationError("source.knowledgeBaseId must be an integer")

    def get_source_knowledge_base_id(self, graph: Dict[str, Any]) -> int:
        validation = self.validate_graph(graph)
        return self.get_source_knowledge_base_id_from_validation(validation)

    def get_retrieve_knowledge_base_id(self, graph: Dict[str, Any]) -> Optional[int]:
        validation = self.validate_graph(graph)
        retrieve_data = validation.nodes_by_type["retrieve"].get("data") or {}
        kb_id = retrieve_data.get("knowledgeBaseId") or retrieve_data.get("knowledge_base_id")
        if kb_id in (None, ""):
            return None
        try:
            return int(kb_id)
        except (TypeError, ValueError):
            raise WorkflowValidationError("retrieve.knowledgeBaseId must be an integer")

    def resolve_knowledge_base_id(self, graph: Dict[str, Any]) -> int:
        validation = self.validate_graph(graph)
        retrieve_data = validation.nodes_by_type["retrieve"].get("data") or {}
        retrieve_kb_id = retrieve_data.get("knowledgeBaseId") or retrieve_data.get("knowledge_base_id")
        if retrieve_kb_id not in (None, ""):
            try:
                return int(retrieve_kb_id)
            except (TypeError, ValueError):
                raise WorkflowValidationError("retrieve.knowledgeBaseId must be an integer")
        return self.get_source_knowledge_base_id_from_validation(validation)

    def get_chunk_config(self, graph: Dict[str, Any]) -> Dict[str, int]:
        validation = self.validate_graph(graph)
        chunk_data = validation.nodes_by_type["chunk"].get("data") or {}
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
