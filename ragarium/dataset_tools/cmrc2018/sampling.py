# ragarium/dataset_tools/cmrc2018/sampling.py

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Union

from utils import YamlConfigReader


# ============================================================
# 基础工具
# ============================================================

def _get_project_root(config: YamlConfigReader) -> Path:
    """
    约定：application.yaml 位于 project-root/config/ 目录下，
    因此 project-root = config_path.parent.parent
    """
    return config.config_path.parent.parent


def _get_cfg(config: Union[YamlConfigReader, str]) -> YamlConfigReader:
    """
    支持直接传入配置路径字符串，内部统一转换为 YamlConfigReader。
    """
    if isinstance(config, str):
        return YamlConfigReader(config)
    return config


def _resolve_raw_file(
    config: YamlConfigReader,
    split: str,
) -> Path:
    """
    解析单个 split 的 raw 文件路径。

    优先级：
      1）dataset.cmrc2018.raw_files.<split>
      2）dataset.cmrc2018.raw_dir + 默认文件名 cmrc2018_<split>.json
    """
    project_root = _get_project_root(config)

    override = config.get(f"dataset.cmrc2018.raw_files.{split}")
    raw_dir = config.get("dataset.cmrc2018.raw_dir") or "datasets/raw"

    if override:
        raw_file = project_root / override
    else:
        raw_file = project_root / raw_dir / f"cmrc2018_{split}.json"

    if not raw_file.exists():
        raise FileNotFoundError(f"未找到 CMRC raw 文件（split={split}）：{raw_file}")

    return raw_file


def _resolve_samples_file(config: YamlConfigReader) -> Path:
    """
    解析 samples 输出文件路径。

    优先级：
      1）dataset.samples_path
      2）dataset.cmrc2018.samples_file（相对 processed_dir 或显式路径）
      3）dataset.cmrc2018.processed_dir + 默认文件名 cmrc2018_samples.json
    """
    project_root = _get_project_root(config)

    # 1）优先使用 dataset.samples_path，作为“全局唯一真值”
    samples_path_cfg = config.get("dataset.samples_path")
    if samples_path_cfg:
        p = Path(samples_path_cfg)
        return p if p.is_absolute() else project_root / p

    # 2）次选 dataset.cmrc2018.samples_file
    samples_file_cfg = config.get("dataset.cmrc2018.samples_file")
    processed_dir = config.get("dataset.cmrc2018.processed_dir") or "datasets/processed"

    if samples_file_cfg:
        p = Path(samples_file_cfg)
        # 如果写成绝对路径，按绝对路径用
        if p.is_absolute():
            return p
        # 如果包含路径分隔符，视为“相对于 project-root 的完整相对路径”
        text = samples_file_cfg
        if "/" in text or "\\" in text:
            return project_root / p
        # 否则视为“文件名”，挂在 processed_dir 下面
        return project_root / processed_dir / text

    # 3）都没配置时的兜底默认值
    return project_root / processed_dir / "cmrc2018_samples.json"


def _get_default_splits(config: YamlConfigReader) -> List[str]:
    """
    默认使用的 splits，配置缺失时使用 ["dev"]。
    """
    splits = config.get("dataset.cmrc2018.splits")
    if isinstance(splits, list) and splits:
        return [str(s) for s in splits]
    return ["dev"]


# ============================================================
# raw 数据加载
# ============================================================

def load_raw_split(
    split: str,
    config: Union[YamlConfigReader, str] = "config/application.yaml",
) -> List[Dict[str, Any]]:
    """
    加载单个 split 的原始 CMRC 数据。
    """
    cfg = _get_cfg(config)
    raw_file = _resolve_raw_file(cfg, split)

    with raw_file.open("r", encoding="utf-8") as f:
        return json.load(f)


def load_raw_multi_splits(
    splits: Sequence[str],
    config: Union[YamlConfigReader, str] = "config/application.yaml",
) -> List[Dict[str, Any]]:
    """
    同时加载多个 split 的原始 CMRC 数据，并简单拼接为一个列表。
    """
    cfg = _get_cfg(config)

    all_rows: List[Dict[str, Any]] = []
    for split in splits:
        data = load_raw_split(split=split, config=cfg)
        all_rows.extend(data)

    return all_rows


# ============================================================
# raw → RAG 样本
# ============================================================

def _cmrc_to_rag_format_for_split(
    raw_data: List[Dict[str, Any]],
    split: str,
    limit: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """
    将单个 split 的 CMRC 原始结构转换为 RAG 评估样本结构。

    输出字段：
      id, split, question, ground_truth, ground_truth_context
    """
    rows: List[Dict[str, Any]] = []

    for item in raw_data:
        ctx = item["context_text"]

        for qa in item["qas"]:
            rows.append(
                {
                    "id": qa["query_id"],
                    "split": split,
                    "question": qa["query_text"],
                    "ground_truth": qa["answers"][0],
                    "ground_truth_context": ctx,
                }
            )

    if limit is not None:
        rows = rows[:limit]

    return rows


def _apply_total_limit(
    rows: List[Dict[str, Any]],
    total_limit: Optional[int],
) -> List[Dict[str, Any]]:
    """
    在合并后的样本上应用总量限制。
    """
    if total_limit is None:
        return rows
    return rows[: total_limit]


# ============================================================
# 构建 eval samples 文件
# ============================================================

def build_eval_samples(
    config: Union[YamlConfigReader, str] = "config/application.yaml",
    splits: Optional[Sequence[str]] = None,
) -> Path:
    """
    从多个 split 的原始 CMRC 数据构建评估样本（samples），写入统一文件。

    参数：
      config:
        YamlConfigReader 或配置路径。
      splits:
        需要使用的 split 列表，例如 ["train", "dev"]。
        如为 None，则从 dataset.cmrc2018.splits 读取，默认 ["dev"]。

    配置项（可选）：
      dataset.samples_path:
        全局 samples 输出路径，若配置则优先使用。
      dataset.cmrc2018.splits:
        默认 splits 列表。
      dataset.cmrc2018.sample_limit_per_split:
        单个 split 截断条数。
      dataset.cmrc2018.total_sample_limit:
        合并后总条数上限。
      dataset.cmrc2018.raw_dir / raw_files.*:
        raw 文件位置。
      dataset.cmrc2018.processed_dir / samples_file:
        输出文件位置的兜底配置。

    行为：
      1）如目标 samples 文件已存在，直接返回。
      2）否则按 split 依次读取 raw，转换为样本并合并写入。
    """
    cfg = _get_cfg(config)

    if splits is None:
        splits = _get_default_splits(cfg)

    samples_file = _resolve_samples_file(cfg)
    if samples_file.exists():
        print(f"[cmrc2018.sampling] 样本已存在：{samples_file}")
        return samples_file

    per_split_limit = cfg.get("dataset.cmrc2018.sample_limit_per_split")
    total_limit = cfg.get("dataset.cmrc2018.total_sample_limit")

    all_samples: List[Dict[str, Any]] = []

    for split in splits:
        raw_data = load_raw_split(split=split, config=cfg)
        rows = _cmrc_to_rag_format_for_split(
            raw_data=raw_data,
            split=split,
            limit=per_split_limit,
        )
        all_samples.extend(rows)

    all_samples = _apply_total_limit(all_samples, total_limit)

    samples_file.parent.mkdir(parents=True, exist_ok=True)
    with samples_file.open("w", encoding="utf-8") as f:
        json.dump(all_samples, f, ensure_ascii=False, indent=2)

    print(
        f"[cmrc2018.sampling] 生成样本：{samples_file}，"
        f"共 {len(all_samples)} 条，splits={list(splits)}"
    )
    return samples_file
