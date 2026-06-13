# ragarium/dataset_tools/__init__.py
"""
dataset_tools 包：数据集适配层。

设计思路：
1. 每个具体数据集作为一个子模块存在，例如：
       ragarium.dataset_tools.cmrc2018
2. 顶层只暴露数据集子模块名称，不直接平铺函数。
   这样可以保持命名空间干净，便于后续扩展多个数据集插件。

当前内置的数据集子模块：
    cmrc2018
        面向 CMRC2018 的原始数据读取、评估样本构建以及 chunk 管线工具。

推荐使用方式：
    from ragarium.dataset_tools import cmrc2018

    samples_path = cmrc2018.build_eval_samples(config)
    samples = cmrc2018.load_eval_samples(config)
    chunks_path = cmrc2018.make_chunks_from_samples(samples_path, chunks_path)
"""

from . import cmrc2018

__all__ = ["cmrc2018"]
