# ragarium/dataset_tools/cmrc2018/chunking.py
"""
chunking：从评估样本中切出向量库用的文本块，并在本地做一次简单去重。

设计目标：
1. 只负责把 samples 里的 ground_truth_context 切成小块，不做复杂清洗。
2. 在“写入 JSONL 之前”做一层非常直接的去重：文本完全相同的 chunk 只保留一份。
3. 代码结构尽量简单，新手打开就能看懂逻辑，知道从哪里下手改。

约定的输入样本字段（samples.json）：
    [
        {
            "id": str,                    # 样本唯一标识
            "question": str,
            "ground_truth": str,
            "ground_truth_context": str   # 将被切分的原文
        },
        ...
    ]

约定的 chunk 记录字段（输出 JSONL，每行一个）：
    {
        "doc_id": str,      # chunk 级别的唯一 ID，例如 "<sample_id>_<序号>"
        "sample_id": str,   # 来自哪个样本 id
        "text": str         # chunk 文本内容
    }

去重规则（尽可能简单）：
    以 text.strip() 作为 key，只要文本完全一致，就认为是重复 chunk。
    如果 A、B 两个 chunk 文本一样，只保留最先出现的那一个。
"""

import json
from pathlib import Path
from typing import Any, Dict, List, Union

from langchain.text_splitter import RecursiveCharacterTextSplitter

# 类型别名只是帮助阅读，不改变实际行为
SampleRecord = Dict[str, Any]
ChunkRecord = Dict[str, Any]


def make_chunks_from_samples(
    samples_path: Union[str, Path],
    chunks_path: Union[str, Path],
    chunk_size: int = 300,
    chunk_overlap: int = 30,
) -> Path:
    """
    将 samples 中的 ground_truth_context 切片，输出为 JSONL chunks 文件。

    参数：
        samples_path:
            JSON 文件路径，内容为 List[SampleRecord]。
            至少需要包含 id 和 ground_truth_context 字段。
        chunks_path:
            输出 JSONL 文件路径，每行一个 ChunkRecord。
        chunk_size:
            文本切片的最大长度，单位是字符。
        chunk_overlap:
            相邻 chunk 之间的重叠长度，单位是字符。

    返回：
        chunks_path（Path 对象）

    行为说明：
        1. 按行写出 JSONL，每个 chunk 一行。
        2. doc_id 采用 "<sample_id>_<序号>" 的形式。
        3. 在写入前做一次“基于文本内容”的去重：
           相同 text 的 chunk 只保留第一条。
    """
    samples_path = Path(samples_path)
    chunks_path = Path(chunks_path)

    with samples_path.open("r", encoding="utf-8") as f:
        samples: List[SampleRecord] = json.load(f)

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        separators=["\n\n", "\n", "。", "；", " "],
    )

    chunks_path.parent.mkdir(parents=True, exist_ok=True)

    # 全局去重集合：记录已经写过的 chunk 文本
    # 说明：
    #   1）使用 text.strip()，去掉首尾空白再比较，避免无意义差异。
    #   2）这是全局去重：不同样本里如果出现完全相同的 chunk，也只保留一份。
    seen_texts = set()

    raw_chunk_count = 0
    written_chunk_count = 0

    with chunks_path.open("w", encoding="utf-8") as f_out:
        for s in samples:
            ctx = s["ground_truth_context"]
            sid = s["id"]

            chunks = splitter.split_text(ctx)
            for i, text in enumerate(chunks):
                raw_chunk_count += 1

                # 规范化文本后用于去重
                normalized = text.strip()
                if not normalized:
                    # 空文本直接跳过
                    continue

                if normalized in seen_texts:
                    # 已经写过同样文本，跳过这条
                    continue

                seen_texts.add(normalized)

                record: ChunkRecord = {
                    "doc_id": f"{sid}_{i}",
                    "sample_id": sid,
                    "text": text,
                }
                f_out.write(json.dumps(record, ensure_ascii=False) + "\n")
                written_chunk_count += 1

    print(
        f"[chunking] 完成切片：{samples_path} → {chunks_path}，"
        f"原始 chunk 数量（含重复）={raw_chunk_count}，"
        f"去重后写入={written_chunk_count}"
    )
    return chunks_path


def load_chunk_records(path: Union[str, Path]) -> List[ChunkRecord]:
    """
    从 JSONL chunks 文件中读取所有 chunk 记录。

    参数：
        path:
            JSONL 文件路径，每行一个 ChunkRecord。

    返回：
        List[ChunkRecord]
    """
    path = Path(path)
    records: List[ChunkRecord] = []

    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            records.append(json.loads(line))

    return records
