# ragarium/dataset_tools/cmrc2018/__init__.py
"""
cmrc2018 数据集工具的公共 API。

主要用途：
1. 从原始 CMRC2018 raw JSON 构建评估样本（samples）。
2. 加载已经构建好的 samples 列表。
3. 读取单个或多个 split 的 raw 数据。
4. 从 samples 生成 chunk 文件，并读取 chunk 记录。

导出的函数说明：

1. build_eval_samples(config: YamlConfigReader | str) -> pathlib.Path
   用途：
       从原始 CMRC2018 数据构建评估样本文件（samples.json）。
   输入：
       config:
           YamlConfigReader 实例，或配置文件路径字符串。
           内部至少需要使用：
               dataset.raw_path       原始数据路径（相对 project_root）
               dataset.samples_path   评估样本输出路径（相对 project_root）
               dataset.sample_limit   可选，样本条数上限
   输出：
       pathlib.Path 对象，指向生成或已存在的 samples.json 文件。
       如果目标文件已存在，则不会重复生成，直接返回路径。

2. load_eval_samples(config: YamlConfigReader | str) -> list[dict]
   用途：
       加载已经构建好的评估样本列表。
   输入：
       config:
           同 build_eval_samples。
           使用 dataset.samples_path 定位 samples 文件。
   输出：
       Python 列表，每个元素是一个 dict，字段约定：
           {
               "id": str,
               "question": str,
               "ground_truth": str,
               "ground_truth_context": str
           }

3. load_raw_split(config: YamlConfigReader, split: str) -> list[dict]
   用途：
       读取单个 split 的 CMRC2018 原始记录。
   输入：
       config:
           YamlConfigReader 实例。
       split:
           字符串，例如 "train"、"dev"、"trial" 等，具体取决于 application.yaml 中的约定。
   输出：
       对应 split 的原始样本列表，每个元素是原始 CMRC2018 的记录结构。

4. load_raw_multi_splits(config: YamlConfigReader, splits: list[str]) -> list[dict]
   用途：
       同时读取多个 split，并在内存中合并为一个列表。
   输入：
       config:
           YamlConfigReader 实例。
       splits:
           split 名称列表，例如 ["train", "dev"]。
   输出：
       多个 split 合并后的原始记录列表。

5. make_chunks_from_samples(
       samples_path: str | pathlib.Path,
       chunks_path: str | pathlib.Path,
       chunk_size: int = 300,
       chunk_overlap: int = 30,
   ) -> pathlib.Path
   用途：
       将评估样本中的 ground_truth_context 切分为 chunk，写成 JSONL 文件。
   输入：
       samples_path:
           已存在的 samples.json 路径。
           JSON 文件内容为列表，每条记录至少包含：
               id, question, ground_truth, ground_truth_context。
       chunks_path:
           chunk 输出文件路径，JSONL 格式，每行一个 chunk 记录。
       chunk_size:
           文本切片的最大长度（字符数）。
       chunk_overlap:
           相邻 chunk 之间的重叠长度（字符数）。
   输出：
       pathlib.Path 对象，指向写入完成的 chunks.jsonl 文件。
   备注：
       当前实现会在写入前做一次基于文本内容的全局去重：
       以 text.strip() 为 key，相同文本的 chunk 只保留第一条。

6. load_chunk_records(path: str | pathlib.Path) -> list[dict]
   用途：
       从 JSONL 格式的 chunk 文件中读取所有 chunk 记录。
   输入：
       path:
           chunks.jsonl 文件路径。
   输出：
       Python 列表，每个元素是一个 dict，字段约定：
           {
               "doc_id": str,
               "sample_id": str,
               "text": str
           }
"""

from .sampling import (
    build_eval_samples,
    load_raw_split,
    load_raw_multi_splits,
)

from .loader import (
    load_eval_samples,
)

from .chunking import (
    make_chunks_from_samples,
    load_chunk_records,
)

__all__ = [
    "build_eval_samples",
    "load_eval_samples",
    "load_raw_split",
    "load_raw_multi_splits",
    "make_chunks_from_samples",
    "load_chunk_records",
]
