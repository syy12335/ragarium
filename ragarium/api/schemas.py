from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class CreateKnowledgeBaseRequest(BaseModel):
    name: str = Field(min_length=1)


class UrlImportRequest(BaseModel):
    url: str = Field(min_length=1)
    chunk_size: Optional[int] = Field(default=None, gt=0)
    chunk_overlap: Optional[int] = Field(default=None, ge=0)


class AppConfigRequest(BaseModel):
    providers: Dict[str, Dict[str, Any]]
    roles: Dict[str, Dict[str, Any]]
    chunk: Dict[str, int]
    api_keys: Dict[str, str] = Field(default_factory=dict)


class IndexRequest(BaseModel):
    overwrite: bool = True


class RetrievalTestRequest(BaseModel):
    query: str = Field(min_length=1)
    top_k: int = Field(default=5, ge=1, le=20)


class WorkflowRequest(BaseModel):
    name: str = Field(min_length=1)
    graph: Dict[str, Any]
    id: Optional[int] = None


class WorkflowRunRequest(BaseModel):
    knowledge_base_id: Optional[int] = None
    question: str = Field(min_length=1)
    k: int = 3


class WorkflowExecuteRequest(BaseModel):
    inputs: Dict[str, Any] = {}


class RuntimeInvokeRequest(BaseModel):
    question: str = ""


class RuntimeBatchRequest(BaseModel):
    questions: List[str] = []


class QueryGenerateRequest(BaseModel):
    knowledge_base_id: int
    examples: List[str]
    target_count: int = Field(gt=0, le=500)
    name: str = "Generated queries"


class EvalRunRequest(BaseModel):
    query_set_id: int
    workflow_id: int
    limit: Optional[int] = None
    metric_names: Optional[List[str]] = None
