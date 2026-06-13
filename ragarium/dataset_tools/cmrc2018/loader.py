# ragarium/dataset_tools/cmrc2018/loader.py

import json
from typing import Any, Dict, List, Union

from utils import YamlConfigReader
from .sampling import _get_cfg, _resolve_samples_file


def load_eval_samples(
    config: Union[YamlConfigReader, str] = "config/application.yaml",
) -> List[Dict[str, Any]]:
    """
    统一的 CMRC 评估样本加载接口。

    仅仅读取 samples JSON 文件，不做任何加工。
    如果文件不存在，提示先调用 build_eval_samples。
    """
    cfg = _get_cfg(config)
    samples_file = _resolve_samples_file(cfg)

    if not samples_file.exists():
        raise FileNotFoundError(
            f"未找到评估样本文件：{samples_file}。"
            "请先调用 build_eval_samples(...) 构建样本。"
        )

    with samples_file.open("r", encoding="utf-8") as f:
        data: List[Dict[str, Any]] = json.load(f)

    return data
