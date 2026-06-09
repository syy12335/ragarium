# rag_eval/vector/vector_builder.py

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from chromadb import PersistentClient
from langchain.schema import Document

from utils import YamlConfigReader
from rag_eval.dataset_tools.cmrc2018 import (
    build_eval_samples,
    make_chunks_from_samples,
    load_chunk_records,
)
from rag_eval.vector.vector_store_manager import VectorStoreManager


PathLike = Union[str, Path]
ConfigLike = Union[YamlConfigReader, str]


def _get_project_root(config: YamlConfigReader) -> Path:
    """
    约定：
        application.yaml 位于 project-root/config/application.yaml，
        因此：
            project_root = config.config_path.parent.parent
    输入：
        config:
            YamlConfigReader 实例。
    输出：
        project_root 的 Path 对象。
    """
    return config.config_path.parent.parent


def _to_abs_path(path: PathLike, project_root: Path) -> Path:
    """
    将传入路径转换为绝对路径。

    输入：
        path:
            字符串或 Path，可以是绝对路径，也可以是相对 project_root 的相对路径。
        project_root:
            项目根目录 Path。

    输出：
        Path 对象：
            若 path 本身为绝对路径，直接返回；
            否则视为相对于 project_root 的路径。
    """
    p = Path(path)
    if p.is_absolute():
        return p
    return project_root / p


def convert_chunks_to_documents(records: List[Dict[str, Any]]) -> List[Document]:
    """
    将 chunk 记录转换为 LangChain Document 列表。

    输入：
        records:
            列表，每条记录至少包含字段：
                text: str       chunk 文本内容
                doc_id: str     chunk 唯一标识
                sample_id: str  对应样本 id

    输出：
        List[Document]：
            page_content = record["text"]
            metadata = {
                "doc_id": record.get("doc_id", ""),
                "sample_id": record.get("sample_id", ""),
            }
    """
    docs: List[Document] = []
    for item in records:
        docs.append(
            Document(
                page_content=item["text"],
                metadata={
                    "doc_id": item.get("doc_id", ""),
                    "sample_id": item.get("sample_id", ""),
                },
            )
        )
    return docs


def convert_product_chunks_to_documents(records: List[Dict[str, Any]]) -> List[Document]:
    """
    Convert product knowledge-base chunks from SQLite into LangChain Documents.

    Product chunks use `content` plus JSON metadata. The older CMRC path uses
    `text`; both are intentionally kept separate so the demo path stays stable.
    """
    docs: List[Document] = []
    for item in records:
        metadata = item.get("metadata") or item.get("metadata_json") or {}
        if isinstance(metadata, str):
            metadata = {"raw_metadata": metadata}
        if "chunk_index" not in metadata and "chunk_index" in item:
            metadata["chunk_index"] = item["chunk_index"]
        if "source_id" not in metadata and "source_id" in item:
            metadata["source_id"] = item["source_id"]
        docs.append(
            Document(
                page_content=item.get("content") or item.get("text") or "",
                metadata=metadata,
            )
        )
    return docs


class VectorDatabaseBuilder:
    """
    VectorDatabaseBuilder：评估样本与 chunk 文件到向量库的统一构建入口。

    设计职责：
        1. 不负责 raw → samples 的细节，仅在必要时调用数据集工具构建。
        2. 不负责 embedding 与底层向量库具体实现，全部委托给 VectorStoreManager。
        3. 对外统一通过 invoke(...) 方法触发构建流程。

    典型用法：

        from rag_eval import VectorDatabaseBuilder

        builder = VectorDatabaseBuilder("config/application.yaml")
        manager = builder.invoke(
            samples_path=None,        # 使用配置中的 dataset.samples_path
            collection_name=None,     # 使用配置中的 vector_store.collection_name
            overwrite=True,           # 若已存在则覆盖
        )

        retriever = manager.get_retriever(
            collection_name=builder._resolve_collection_name(),
            k=3,
        )

    构造函数输入：
        config: ConfigLike
            可以是 YamlConfigReader 实例，或配置文件路径字符串。
            字符串形式时，会自动构造 YamlConfigReader。

    invoke 方法输入：
        samples_path: Optional[PathLike]
            可选。显式指定评估样本文件路径（JSON 列表格式）。
            若为 None，则根据 application.yaml 的 dataset.samples_path 解析。
        collection_name: Optional[str]
            可选。显式指定向量库 collection 名称。
            若为 None，则从 application.yaml 的 vector_store.collection_name 读取。
        overwrite: bool
            当目标 collection 已存在时：
                False：直接返回，不做任何修改。
                True：删除原有 collection 并重新构建。

    invoke 返回值：
        VectorStoreManager 实例（与构造时使用同一配置），
        其中已写入构建完成的向量库，可继续用于检索。
    """

    def __init__(self, config: ConfigLike = "config/application.yaml") -> None:
        if isinstance(config, str):
            config = YamlConfigReader(config)
        self.config: YamlConfigReader = config
        self.project_root: Path = _get_project_root(self.config)
        self.manager = VectorStoreManager(self.config)

    # ------------------------------------------------------------------
    # 内部工具：配置解析
    # ------------------------------------------------------------------

    def _resolve_collection_name(self, explicit: Optional[str] = None) -> str:
        """
        解析向量库 collection 名称。

        输入：
            explicit:
                可选。显式指定的 collection_name。
        输出：
            最终使用的 collection_name 字符串。
        规则：
            1. 若 explicit 非空，则优先使用 explicit。
            2. 否则尝试从配置中读取 vector_store.collection_name。
            3. 若仍为空，则抛出 ValueError。
        """
        if explicit:
            return explicit

        collection = self.config.get("vector_store.collection_name")
        if not collection:
            raise ValueError(
                "配置缺少 vector_store.collection_name，且未显式指定 collection_name"
            )
        return collection

    def _resolve_samples_path(self) -> Path:
        """
        基于配置解析 samples 文件路径，必要时自动构建。

        输入：
            无（使用构造函数传入的 self.config）。
        输出：
            Path 对象，指向 samples.json 文件。
        行为：
            1. 从 dataset.samples_path 读取相对路径。
            2. 若文件不存在，则调用 build_eval_samples(self.config) 重新构建。
        """
        samples_rel = self.config.get("dataset.samples_path")
        if not samples_rel:
            raise ValueError("配置缺少 dataset.samples_path")

        samples_path = self.project_root / samples_rel
        if not samples_path.exists():
            print(f"[vector_builder] 样本不存在，先构建 samples：{samples_path}")
            samples_path = build_eval_samples(self.config)

        return samples_path

    def _resolve_chunks_path(self) -> Path:
        """
        基于配置解析 chunks 文件路径，必要时自动构建。

        输入：
            无（使用构造函数传入的 self.config）。
        输出：
            Path 对象，指向 chunks.jsonl 文件。
        行为：
            1. 从 dataset.chunks_path 读取相对路径。
            2. 若文件不存在，则先确保 samples 存在，再调用 make_chunks_from_samples 构建。
        """
        chunks_rel = self.config.get("dataset.chunks_path")
        if not chunks_rel:
            raise ValueError("配置缺少 dataset.chunks_path")

        chunks_path = self.project_root / chunks_rel
        if not chunks_path.exists():
            samples_path = self._resolve_samples_path()
            print(f"[vector_builder] 使用 samples 切割 chunks → {chunks_path}")
            make_chunks_from_samples(samples_path, chunks_path)

        return chunks_path

    def _collection_exists(self, collection_name: str) -> bool:
        """
        检查目标 collection 是否已存在于当前持久化目录。

        输入：
            collection_name:
                目标 collection 名称。
        输出：
            bool：
                True  表示已存在；
                False 表示不存在。
        """
        persist_dir = Path(self.manager.persist_directory)
        client = PersistentClient(path=str(persist_dir))
        existing = [c.name for c in client.list_collections()]
        return collection_name in existing

    # ------------------------------------------------------------------
    # 核心入口：invoke
    # ------------------------------------------------------------------

    def invoke(
        self,
        samples_path: Optional[PathLike] = None,
        collection_name: Optional[str] = None,
        overwrite: bool = False,
    ) -> VectorStoreManager:
        """
        构建向量库的统一入口。

        输入：
            samples_path:
                可选。显式指定评估样本文件路径（JSON 列表格式）。
                若为 None，则使用配置中的 dataset.samples_path。
            collection_name:
                可选。显式指定 collection 名称。
                若为 None，则使用配置中的 vector_store.collection_name。
            overwrite:
                当目标 collection 已存在时：
                    False：直接返回，不做任何修改。
                    True：删除原有 collection 并重新构建。

        输出：
            VectorStoreManager 实例（与构造时同配置），
            向量库已经完成构建，可直接用于检索。
        """
        coll = self._resolve_collection_name(collection_name)

        # 1. 处理 collection 是否已存在
        persist_dir = Path(self.manager.persist_directory)
        client = PersistentClient(path=str(persist_dir))
        existing_collections = [c.name for c in client.list_collections()]

        if coll in existing_collections:
            if not overwrite:
                print(
                    f"[vector_builder] 向量库已存在，直接返回：{persist_dir} "
                    f"(collection='{coll}')"
                )
                return self.manager
            print(
                f"[vector_builder] 覆盖模式：删除已有 collection='{coll}'"
            )
            client.delete_collection(name=coll)

        # 2. 解析 samples / chunks 路径
        if samples_path is not None:
            # path 模式：由调用方显式指定 samples 文件
            samples_abs = _to_abs_path(samples_path, self.project_root)
            if not samples_abs.exists():
                raise FileNotFoundError(f"未找到样本文件：{samples_abs}")

            chunks_path = samples_abs.with_name(samples_abs.stem + "_chunks.jsonl")
            print(f"[vector_builder] 使用 samples 切割 chunks → {chunks_path}")
            make_chunks_from_samples(samples_abs, chunks_path)
        else:
            # 配置驱动模式：使用 dataset.* 配置解析
            chunks_path = self._resolve_chunks_path()

        # 3. 读取 chunks → Document → 写入向量库
        records = load_chunk_records(chunks_path)
        docs = convert_chunks_to_documents(records)

        print(
            f"[vector_builder] 写入向量库（共 {len(docs)} 条 chunk），"
            f"collection='{coll}'"
        )
        self.manager.add_documents(docs, collection_name=coll)

        print("[vector_builder] 向量库构建完成")
        return self.manager

    def build_from_chunks(
        self,
        chunk_records: List[Dict[str, Any]],
        *,
        collection_name: str,
        overwrite: bool = True,
    ) -> VectorStoreManager:
        """
        Build a Chroma collection from product knowledge-base chunk records.

        This is the product path used by the FastAPI app. The legacy `invoke`
        method remains the CMRC demo-compatible path.
        """
        if not chunk_records:
            raise ValueError("chunk_records is empty; cannot build vector store")

        coll = self._resolve_collection_name(collection_name)
        if overwrite:
            self.manager.delete_collection(coll)
        elif self._collection_exists(coll):
            return self.manager

        docs = convert_product_chunks_to_documents(chunk_records)
        docs = [doc for doc in docs if doc.page_content.strip()]
        if not docs:
            raise ValueError("all chunks are empty; cannot build vector store")

        print(
            f"[vector_builder] 写入产品知识库向量库（共 {len(docs)} 条 chunk），"
            f"collection='{coll}'"
        )
        self.manager.add_documents(docs, collection_name=coll)
        print("[vector_builder] 产品知识库向量库构建完成")
        return self.manager


# ----------------------------------------------------------------------
# 兼容性函数：保留简化入口，内部统一调用 VectorDatabaseBuilder
# ----------------------------------------------------------------------

def ensure_cmrc_vector_store(
    config: ConfigLike = "config/application.yaml",
) -> None:
    """
    CMRC 专用入口（配置驱动版本）。

    行为：
        1. 使用 application.yaml 中的 dataset.* 和 vector_store.* 配置。
        2. 若目标 collection 已存在，则直接返回。
        3. 若 samples / chunks 缺失，则按配置约定自动构建。
        4. 通过 VectorDatabaseBuilder.invoke 完成向量库写入。
    """
    if isinstance(config, str):
        config = YamlConfigReader(config)

    builder = VectorDatabaseBuilder(config)
    collection_name = builder._resolve_collection_name()

    if builder._collection_exists(collection_name):
        persist_dir = Path(builder.manager.persist_directory)
        print(
            f"[vector_builder] 向量库已存在：{persist_dir} "
            f"(collection='{collection_name}')"
        )
        return

    builder.invoke()


def build_vector_store_from_samples(
    samples_path: PathLike,
    config_path: str = "config/application.yaml",
    collection_name: Optional[str] = None,
    overwrite: bool = False,
) -> None:
    """
    通用入口：传入一个“评估样本”文件路径，自动切 chunk 并构建向量库。

    输入：
        samples_path:
            JSON 格式的评估样本文件路径。
            数据格式需满足 data_standard_README 中定义的 samples 结构。
        config_path:
            application.yaml 的路径字符串。
        collection_name:
            可选。显式指定向量库 collection 名称；
            若为 None，则从配置中的 vector_store.collection_name 读取。
        overwrite:
            bool。当目标 collection 已存在时是否覆盖。

    输出：
        无。函数执行完成即表示向量库已构建完毕。
    """
    builder = VectorDatabaseBuilder(config_path)
    builder.invoke(
        samples_path=samples_path,
        collection_name=collection_name,
        overwrite=overwrite,
    )


def build_cmrc_dataset_and_vector_store(
    config_path: str = "config/application.yaml",
) -> None:
    """
    一键执行 CMRC 全流程（适合作为脚手架入口）：

        1. raw → samples
        2. samples → chunks
        3. chunks → VectorStore

    等价于：
        config = YamlConfigReader(config_path)
        build_eval_samples(config)
        ensure_cmrc_vector_store(config)

    输入：
        config_path:
            application.yaml 配置文件路径。

    输出：
        无。函数执行完成即表示数据与向量库均已构建完毕。
    """
    config = YamlConfigReader(config_path)
    build_eval_samples(config)
    ensure_cmrc_vector_store(config)
