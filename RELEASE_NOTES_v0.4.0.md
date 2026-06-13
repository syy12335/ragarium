# Ragarium v0.4.0

This release renames the project from `rag-eval-scaffold` to **Ragarium** and resets the project positioning around a local-first RAG workspace.

Ragarium is no longer presented as a scaffold. It is a local RAG workspace for building, testing, evaluating, and exposing RAG workflows.

## Highlights

- New product identity: `Ragarium`.
- New Python package name: `ragarium`.
- New backend command: `ragarium-api`.
- Updated README and frontend branding around a local-first RAG workflow.
- Runtime API metadata now reports `ragarium-runtime`.

## Workflow

Ragarium focuses on the local loop:

```text
Document ingestion -> Knowledge-base indexing -> RAG Workflow -> Query generation -> Evaluation -> Runtime API
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
