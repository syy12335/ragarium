from __future__ import annotations

from copy import deepcopy

import pytest

from rag_eval.workflow import DEFAULT_WORKFLOW_GRAPH, WorkflowEngine, WorkflowValidationError


def graph_with_source_db(kb_id: str = "7"):
    graph = deepcopy(DEFAULT_WORKFLOW_GRAPH)
    for node in graph["nodes"]:
        if node["type"] == "source":
            node["data"]["knowledgeBaseId"] = kb_id
    return graph


def test_valid_default_workflow_passes():
    graph = graph_with_source_db()
    result = WorkflowEngine().validate_graph(graph)

    assert result.node_ids_by_type["source"] == "source"
    assert result.node_ids_by_type["answer"] == "answer"
    assert WorkflowEngine().get_source_knowledge_base_id(graph) == 7


def test_source_db_is_required():
    with pytest.raises(WorkflowValidationError, match="Source DB node must select"):
        WorkflowEngine().validate_graph(DEFAULT_WORKFLOW_GRAPH)


def test_missing_required_edge_fails():
    graph = graph_with_source_db()
    graph = {
        "nodes": graph["nodes"],
        "edges": graph["edges"][:-1],
    }

    with pytest.raises(WorkflowValidationError, match="prompt_llm -> answer"):
        WorkflowEngine().validate_graph(graph)


def test_unexpected_edge_fails():
    graph = graph_with_source_db()
    graph["edges"] = [
        *graph["edges"],
        {"id": "source-answer", "source": "source", "target": "answer"},
    ]

    with pytest.raises(WorkflowValidationError, match="canonical Source"):
        WorkflowEngine().validate_graph(graph)


def test_fake_retriever_and_generator_run_question():
    engine = WorkflowEngine()
    graph = graph_with_source_db()

    result = engine.run_question(
        graph,
        question="How do I import docs?",
        retriever=lambda question: [{"content": "Use the Knowledge import panel."}],
        generator=lambda question, contexts: f"{question} => {contexts[0]}",
    )

    assert result["question"] == "How do I import docs?"
    assert result["contexts"] == ["Use the Knowledge import panel."]
    assert "Knowledge import" in result["answer"]


def test_retrieve_node_can_select_knowledge_base():
    graph = graph_with_source_db("7")
    for node in graph["nodes"]:
        if node["type"] == "retrieve":
            node["data"]["knowledgeBaseId"] = "42"

    assert WorkflowEngine().get_retrieve_knowledge_base_id(graph) == 42
    assert WorkflowEngine().resolve_knowledge_base_id(graph) == 42


def test_retrieve_inherits_source_db_when_empty():
    graph = graph_with_source_db("11")

    assert WorkflowEngine().resolve_knowledge_base_id(graph) == 11
