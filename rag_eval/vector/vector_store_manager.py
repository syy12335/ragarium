# rag_eval/vector/vector_store_manager.py

from __future__ import annotations

import logging
from pathlib import Path
from typing import List, Optional

from chromadb import PersistentClient
from langchain.schema import Document
from langchain_community.vectorstores import Chroma
from langchain_core.embeddings import Embeddings

from utils import YamlConfigReader
from rag_eval.embeddings.factory import build_embedding_from_config


logger = logging.getLogger(__name__)


class VectorStoreManager:
    """
    VectorStoreManager：管理 Chroma 向量库。

    职责边界：
      1）解析向量库路径与默认 collection 名称
      2）创建 / 复用 / 删除 Chroma collection
      3）写入 Document，提供 retriever 与统一检索入口 invoke

    Embedding 通过构造函数注入，或由 embedding_factory 统一创建，
    不在这里出现任何 provider / 模型名，只依赖配置与注入结果。
    """

    def __init__(
        self,
        config: YamlConfigReader | None = None,
        embedding: Optional[Embeddings] = None,
    ) -> None:
        # 1. 配置加载
        if config is None:
            config = YamlConfigReader("config/application.yaml")
        self.config = config

        # 2. 项目根目录：config/application.yaml 位于 project-root/config
        self.project_root: Path = self.config.config_path.parent.parent

        # 3. 向量库持久化目录（vector_store.persist_directory）
        persist_rel = self.config.get("vector_store.persist_directory")
        if not persist_rel:
            raise ValueError("配置缺少 vector_store.persist_directory")
        self.persist_directory: str = str(self.project_root / persist_rel)

        # 4. 默认 collection 名称（vector_store.collection_name）
        default_coll = self.config.get("vector_store.collection_name")
        if not default_coll:
            raise ValueError("配置缺少 vector_store.collection_name")
        self.default_collection_name: str = default_coll

        # 5. Embedding 后端
        if embedding is not None:
            self.embedding: Embeddings = embedding
        else:
            # 由 embedding_factory 基于 application.yaml + model_roles.yaml 构造
            self.embedding = build_embedding_from_config(self.config)

        # 6. 当前绑定的 Chroma 实例（延迟创建，按 collection_name 切换）
        self.vectorstore: Optional[Chroma] = None

    # ============================================================
    # 内部：collection 管理
    # ============================================================
    def load_or_create_collection(self, collection_name: str) -> Chroma:
        """
        保证返回一个绑定到指定 collection_name 的 Chroma 实例。
        如果当前实例已经绑定到同名 collection，则直接复用。
        """
        if (
            self.vectorstore is not None
            and getattr(self.vectorstore, "_collection", None) is not None
            and self.vectorstore._collection.name == collection_name
        ):
            return self.vectorstore

        self.vectorstore = Chroma(
            collection_name=collection_name,
            embedding_function=self.embedding,
            persist_directory=self.persist_directory,
        )
        return self.vectorstore

    # ============================================================
    # 写入与检索基础接口
    # ============================================================
    def add_documents(
        self,
        documents: List[Document],
        collection_name: str,
        batch_size: int = 10,
    ) -> None:
        """
        向指定 collection 写入一批 Document。
        默认按 batch_size 分批写入，避免一次性过大。
        """
        if not documents:
            return

        vs = self.load_or_create_collection(collection_name)

        total = len(documents)
        for i in range(0, total, batch_size):
            batch = documents[i : i + batch_size]
            logger.info(
                "Writing documents %s-%s / %s",
                i + 1,
                min(i + batch_size, total),
                total,
            )
            vs.add_documents(batch)

    def get_retriever(self, collection_name: str, k: int = 3):
        """
        返回一个 LangChain retriever，用于上层 RAG 组件使用。
        """
        vs = self.load_or_create_collection(collection_name)
        return vs.as_retriever(search_type="similarity", search_kwargs={"k": k})

    def delete_collection(self, collection_name: str) -> None:
        """
        删除指定 collection。若不存在，则只打印提示不报错。
        """
        client = PersistentClient(path=self.persist_directory)
        existing_collections = [col.name for col in client.list_collections()]

        if collection_name not in existing_collections:
            logger.info("Collection %s does not exist; skip delete", collection_name)
            return

        client.delete_collection(name=collection_name)
        logger.info("Deleted collection %s", collection_name)

        if (
            self.vectorstore
            and getattr(self.vectorstore, "_collection", None)
            and getattr(self.vectorstore._collection, "name", None) == collection_name
        ):
            self.vectorstore = None

    # ============================================================
    # 统一检索入口：invoke()
    # ============================================================
    def invoke(
        self,
        query: str,
        *,
        k: int = 3,
        collection_name: Optional[str] = None,
    ) -> List[Document]:
        """
        invoke：对外统一检索接口。

        语义：
          输入 query，使用指定或默认 collection 进行相似度检索，
          返回 top-k 相似 Document 列表。
        """
        coll = collection_name or self.default_collection_name
        retriever = self.get_retriever(collection_name=coll, k=k)

        # 新写法：使用 LangChain 推荐的 retriever.invoke，而不是 get_relevant_documents
        results = retriever.invoke(query)

        logger.info(
            "Retriever invoke completed: collection=%s, k=%s, hits=%s",
            coll,
            k,
            len(results),
        )
        return results
