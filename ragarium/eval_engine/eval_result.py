# ragarium/eval_engine/eval_result.py

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional

from pathlib import Path

import pandas as pd
from datasets import Dataset


@dataclass
class EvalResult:
    """
    EvalResult：RAG 评估结果的统一封装。

    字段：
      overall:
        指标名称到分数的映射，例如：
          {
            "faithfulness": 0.87,
            "answer_relevancy": 0.91,
            ...
          }

      per_sample:
        每条样本的明细结果，索引为样本行号，列通常包括：
          question, answer, contexts, ground_truth,
          faithfulness, answer_relevancy, context_precision, context_recall, ...

      dataset:
        传给 ragas.evaluate 的原始 Dataset 对象，便于后续复用。

      csv_path:
        若评估结果已写入 CSV，则记录实际保存路径；否则为 None。

      raw_result:
        ragas.evaluate 返回的原始结果对象，保留以便深度调试或二次处理。
    """

    overall: Dict[str, Optional[float]]
    per_sample: pd.DataFrame
    dataset: Dataset
    csv_path: Optional[str] = None
    raw_result: Any = None

    def to_dataframe(self) -> pd.DataFrame:
        """
        返回逐样本结果的 DataFrame 视图。
        """
        return self.per_sample

    def to_dict(self) -> Dict[str, Any]:
        """
        将整体结果转换为易于序列化的字典结构。
        per_sample 将被转换为 records 形式的列表。
        """
        return {
            "overall": self.overall,
            "per_sample": self.per_sample.to_dict(orient="records"),
            "csv_path": self.csv_path,
        }

    def to_csv(
        self,
        path: Optional[str] = None,
        encoding: str = "utf-8-sig",
        index: bool = False,
    ) -> str:
        """
        将逐样本结果写入 CSV 文件。

        参数：
          path:
            若指定，则以该路径为准；
            若不指定，则使用 EvalResult.csv_path；
            若两者都为空，则抛出异常。

          encoding:
            文件编码，默认 utf-8-sig，方便在 Excel 中直接打开。

          index:
            是否将 DataFrame 索引写入 CSV，默认 False。

        返回：
          最终写入的绝对路径字符串。
        """
        final_path = path or self.csv_path
        if final_path is None:
            raise ValueError(
                "未指定保存路径，且 EvalResult.csv_path 为空，无法写出 CSV。"
            )

        p = Path(final_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        self.per_sample.to_csv(p, index=index, encoding=encoding)
        self.csv_path = str(p.resolve())
        return self.csv_path

    def show_console(self, top_n: int = 5) -> None:
        """
        在命令行中打印整体指标与前若干条样本。

        参数：
          top_n:
            展示前多少条样本的明细。
        """
        print("=== Overall Metrics ===")
        for name, value in self.overall.items():
            try:
                print(f"{name}: {value:.4f}")
            except TypeError:
                print(f"{name}: {value}")

        print()
        print(f"=== Per-sample Metrics (top {top_n}) ===")
        print(self.per_sample.head(top_n))

    def show_streamlit(
        self,
        top_n: int = 5,
        show_bar: bool = True,
    ) -> None:
        """
        使用 Streamlit 展示评估结果。

        参数：
          top_n:
            展示前多少条样本的明细。
          show_bar:
            是否对 overall 数值指标绘制柱状图。

        需要预先安装 streamlit：pip install streamlit
        """
        try:
            import streamlit as st
        except ImportError:
            raise ImportError(
                "使用 show_streamlit() 需要安装 streamlit：pip install streamlit"
            )

        st.subheader("RAGAS Overall Metrics")

        # 只保留数值型指标，便于绘制柱状图
        numeric_overall: Dict[str, float] = {}
        for k, v in self.overall.items():
            if isinstance(v, (int, float)):
                numeric_overall[k] = float(v)

        # 原始 overall 字典完整展示一份
        st.write(self.overall)

        # 可选柱状图视图
        if show_bar and numeric_overall:
            df_overall = pd.DataFrame.from_dict(
                numeric_overall, orient="index", columns=["score"]
            )
            df_overall.index.name = "metric"
            st.bar_chart(df_overall)

        st.subheader(f"Per-sample Metrics (top {top_n})")
        st.dataframe(self.per_sample.head(top_n))

        if self.csv_path:
            st.info(f"逐样本结果已写入 CSV：{self.csv_path}")
