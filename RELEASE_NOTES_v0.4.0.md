# Ragarium v0.4.0

This release renames the project from `rag-eval-scaffold` to **Ragarium** and resets the project positioning around a local-first RAG workspace.

Ragarium is no longer presented as a scaffold. It is a visual local RAG workflow studio for building, evaluating, and exposing RAG workflows as local HTTP APIs.

## Highlights

- Visual RAG workflow canvas for composing retrieval, prompt, answer, query generation, and evaluation steps.
- Automatic query-only evaluation set generation from a selected knowledge base and a few example questions.
- Built-in RAGAS evaluation runs with per-sample answers, contexts, and metric scores.
- Local HTTP Runtime API that exposes prepared workflows through `invoke` and `batch`.
- New product identity, Python package, and backend command: `Ragarium`, `ragarium`, and `ragarium-api`.

## Workflow

Ragarium focuses on the local loop:

```text
Document ingestion -> Knowledge-base indexing -> Visual RAG Workflow -> Query-set generation -> RAGAS evaluation -> Local HTTP Runtime API
```

The evaluation system remains an important part of the product, but it is now presented as part of the complete RAG workflow instead of being the only identity of the project.

## Breaking Changes

- `import rag_eval` is no longer supported.
- `rag-eval-api` is no longer installed.
- Uvicorn entrypoint changed to `ragarium.api.app:app`.
- CLI environment variables changed to `RAGARIUM_HOST`, `RAGARIUM_PORT`, and `RAGARIUM_RELOAD`.
- Local app state override changed to `RAGARIUM_APP_HOME`.

## Compatibility Notes

HTTP API paths and request/response shapes are unchanged.

The repository may still be hosted under the previous GitHub repository name until the remote repository is renamed separately.
