from __future__ import annotations

from typing import Any, Dict, List

from .loaders import ParsedDocument


def chunk_document(
    document: ParsedDocument,
    *,
    chunk_size: int = 900,
    chunk_overlap: int = 120,
) -> List[Dict[str, Any]]:
    if chunk_size <= 0:
        raise ValueError("chunk_size must be positive")
    if chunk_overlap < 0 or chunk_overlap >= chunk_size:
        raise ValueError("chunk_overlap must be >= 0 and smaller than chunk_size")

    text = document.content.strip()
    if not text:
        return []

    chunks: List[Dict[str, Any]] = []
    start = 0
    index = 0
    while start < len(text):
        end = min(start + chunk_size, len(text))
        piece = text[start:end].strip()
        if piece:
            metadata = dict(document.metadata)
            metadata["chunk_index"] = index
            chunks.append(
                {
                    "content": piece,
                    "chunk_index": index,
                    "metadata": metadata,
                }
            )
            index += 1
        if end >= len(text):
            break
        start = max(end - chunk_overlap, start + 1)
    return chunks
