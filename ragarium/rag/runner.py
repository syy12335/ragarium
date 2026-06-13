# ragarium/rag/runner.py

from typing import Dict, Callable, Any

from ragarium.vector.vector_store_manager import VectorStoreManager
from ragarium.rag.normal_rag import NormalRag
from utils import YamlConfigReader


def _normal_rag_factory(
    vector_manager: VectorStoreManager,
    config_path: str,
) -> Any:
    """
    默认的普通 RAG 构造函数：

      1. 从 application.yaml 读取默认的 collection_name
      2. 用 VectorStoreManager.get_retriever(collection_name) 拿到 retriever
      3. 用 retriever + config_path 实例化 NormalRag
    """
    cfg = YamlConfigReader(config_path)
    collection_name = cfg.get("vector_store.collection_name")
    if not collection_name:
        raise ValueError("application.yaml 中缺少 vector_store.collection_name 配置")

    retriever = vector_manager.get_retriever(collection_name)
    return NormalRag(
        retriever=retriever,
        config_path=config_path,
    )


class RagRunner:
    """
    RAG 工作流统一入口（注册表版本）。

      1. 内部维护一个 name -> factory 的注册表：
         - key: rag_type 名称（例如 "normal_rag"）
         - value: 接收 (vector_manager, config_path) 并返回具体 RAG 实例的工厂函数

      2. 当前默认只注册了 "normal" / "normal_rag" → NormalRag。
      3. 对外只暴露统一的 invoke(question: str) -> dict 接口。
    """

    _registry: Dict[str, Callable[[VectorStoreManager, str], Any]] = {
        "normal_rag": _normal_rag_factory,
    }

    def __init__(
        self,
        vector_manager: VectorStoreManager,
        rag_type: str = "normal_rag",
        config_path: str = "config/application.yaml",
    ) -> None:
        try:
            factory = self._registry[rag_type]
        except KeyError:
            raise ValueError(f"未注册的 rag_type：{rag_type}") from None

        self._impl = factory(vector_manager, config_path)

    @classmethod
    def register(
        cls,
        rag_type: str,
        factory: Callable[[VectorStoreManager, str], Any],
    ) -> None:
        """
        注册新的 RAG 实现。

        要求：
          factory 接收 (vector_manager, config_path)，返回一个
          具备 invoke(question: str) -> dict 方法的对象。
        """
        cls._registry[rag_type] = factory

    def invoke(self, question: str) -> Dict[str, Any]:
        return self._impl.invoke(question)
