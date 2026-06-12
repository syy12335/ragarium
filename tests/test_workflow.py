from __future__ import annotations

from copy import deepcopy

import pytest

from rag_eval.workflow import (
    DEFAULT_WORKFLOW_GRAPH,
    WorkflowEngine,
    WorkflowValidationError,
    get_default_workflow_graph,
    get_workflow_templates,
)


def graph_with_source_db(kb_id: str = "7"):
    graph = deepcopy(DEFAULT_WORKFLOW_GRAPH)
    for node in graph["nodes"]:
        if node["type"] == "source":
            node["data"]["knowledgeBaseId"] = kb_id
    return graph


def configured_template_graph(template_id: str, kb_id: str = "7"):
    graph = get_default_workflow_graph(template_id)
    for node in graph["nodes"]:
        if node["type"] in {"source", "query_generate"}:
            node["data"]["knowledgeBaseId"] = kb_id
        if node["type"] == "retrieve" and template_id == "rag":
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


def test_all_workflow_templates_validate_after_required_db_is_selected():
    engine = WorkflowEngine()

    for template in get_workflow_templates():
        if template["id"] == "blank":
            result = engine.validate_graph_structure(template["graph"])
            assert result.template_id == "blank"
            continue
        graph = configured_template_graph(template["id"])
        result = engine.validate_graph(graph)
        assert result.template_id == template["id"]


def test_blank_graph_is_a_draft_but_not_executable():
    graph = get_default_workflow_graph("blank")
    engine = WorkflowEngine()

    assert engine.validate_graph_structure(graph).template_id == "blank"
    with pytest.raises(WorkflowValidationError, match="at least one executable node"):
        engine.validate_graph(graph)


def test_rag_template_requires_retrieve_db():
    graph = get_default_workflow_graph("rag")

    with pytest.raises(WorkflowValidationError, match="Retrieve node must select"):
        WorkflowEngine().validate_graph(graph)


def test_evaluation_template_validates_query_generate_examples():
    graph = configured_template_graph("evaluation")
    for node in graph["nodes"]:
        if node["type"] == "query_generate":
            node["data"]["examples"] = ["一个问题", "两个问题"]

    with pytest.raises(WorkflowValidationError, match="3 to 5"):
        WorkflowEngine().validate_graph(graph)


def test_evaluation_template_retrieve_inherits_or_overrides_query_generate_db():
    graph = configured_template_graph("evaluation", "21")
    engine = WorkflowEngine()

    assert engine.resolve_knowledge_base_id(graph) == 21

    for node in graph["nodes"]:
        if node["type"] == "retrieve":
            node["data"]["knowledgeBaseId"] = "42"

    assert engine.resolve_knowledge_base_id(graph) == 42


def test_ragas_eval_requires_answer_node():
    graph = configured_template_graph("evaluation", "21")
    graph["nodes"] = [node for node in graph["nodes"] if node["type"] != "answer"]
    graph["edges"] = [
        edge
        for edge in graph["edges"]
        if edge["source"] != "answer" and edge["target"] != "answer"
    ]
    graph["edges"].append({"id": "prompt-ragas_eval", "source": "prompt", "target": "ragas_eval"})

    with pytest.raises(WorkflowValidationError, match="Answer node"):
        WorkflowEngine().validate_graph(graph)


def test_ragas_eval_accepts_custom_reference_free_metrics():
    graph = configured_template_graph("evaluation", "21")
    for node in graph["nodes"]:
        if node["type"] == "ragas_eval":
            node["data"]["metricNames"] = ["faithfulness"]

    config = WorkflowEngine().get_eval_config(graph)

    assert config["metric_names"] == ["faithfulness"]
    assert config["metric_preset"] == "custom"


def test_ragas_eval_rejects_unknown_metrics():
    graph = configured_template_graph("evaluation", "21")
    for node in graph["nodes"]:
        if node["type"] == "ragas_eval":
            node["data"]["metricNames"] = ["missing_metric"]

    with pytest.raises(WorkflowValidationError, match="unknown RAGAS metric"):
        WorkflowEngine().get_eval_config(graph)
