"""
Ragarium Console 前端（基于 ragarium 的对外 API）

逻辑约定：
  1. 先通过 VectorDatabaseBuilder 构建 / 刷新向量库；
  2. 基于向量库构造 RagRunner；
  3. 批量评估统一使用 EvalEngine().invoke(runner)，
     样本数上限由 application.yaml.evaluation.sample_limit 控制。
"""

from __future__ import annotations

from typing import Any, Dict

import sys
import time
from pathlib import Path

import pandas as pd
import streamlit as st

# ------------------------------------------------------------
# 让 Python 能找到项目根目录下的 ragarium 包
# ------------------------------------------------------------
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.append(str(ROOT))

from ragarium import (                # noqa: E402
    VectorDatabaseBuilder,
    RagRunner,
    EvalEngine,
)


# ------------------------------------------------------------
# 向量库构建 + Runner 管理
# ------------------------------------------------------------
def build_or_refresh_runner(config_path: str, overwrite: bool = True) -> RagRunner:
    """
    基于指定的 application.yaml 构建 / 刷新向量库，并返回对应的 RagRunner。
    """
    builder = VectorDatabaseBuilder(config_path)
    vector_manager = builder.invoke(overwrite=overwrite)

    runner = RagRunner(vector_manager, rag_type="normal_rag")

    st.session_state["vector_manager"] = vector_manager
    st.session_state["runner"] = runner
    st.session_state["runner_config_path"] = config_path
    st.session_state["db_ready"] = True

    return runner


def get_runner(config_path: str) -> RagRunner:
    """
    从 session_state 中取出已构建好的 RagRunner。

    若尚未构建或配置文件不一致，则抛出异常提示先构建向量库。
    """
    db_ready = st.session_state.get("db_ready", False)
    runner = st.session_state.get("runner")
    stored_cfg = st.session_state.get("runner_config_path")

    if db_ready and runner is not None and stored_cfg == config_path:
        return runner

    raise RuntimeError(
        "当前配置下的向量库尚未构建或已失效，请先在左侧点击“构建 / 刷新向量库”。"
    )


# ------------------------------------------------------------
# 批量评估：EvalEngine().invoke(runner)
# ------------------------------------------------------------
def run_batch_evaluation(
    config_path: str,
) -> Any:
    """
    使用 EvalEngine 统一完成“批量跑 RAG + RAGAS 评估”。

    参数：
      config_path
        application.yaml 路径。

    样本数上限由 application.yaml.evaluation.sample_limit 控制：
        sample_limit > 0  只评估前 sample_limit 条；
        sample_limit == 0 或未配置  评估全部样本。
    """
    runner = get_runner(config_path)

    engine = EvalEngine(config_path=config_path)

    start = time.perf_counter()
    with st.spinner("正在执行 RAG 评估（批量生成答案 + RAGAS 评分）…"):
        result = engine.invoke(runner)
    end = time.perf_counter()

    duration = end - start
    st.info(f"评估完成，整体耗时约 {duration:.1f} 秒")

    return result


# ------------------------------------------------------------
# Streamlit 主体
# ------------------------------------------------------------
def main() -> None:
    st.set_page_config(
        page_title="Ragarium Console",
        layout="wide",
    )

    st.title("RAG 评估控制台")

    # 初始化 session_state
    for key, default in [
        ("eval_result", None),
        ("eval_per_sample", None),
        ("eval_overall", None),
        ("eval_csv_path", None),
        ("runner", None),
        ("runner_config_path", None),
        ("db_ready", False),
    ]:
        if key not in st.session_state:
            st.session_state[key] = default

    # 侧边栏全局配置
    st.sidebar.header("全局配置")

    default_config_path = "config/application.yaml"
    config_path = st.sidebar.text_input(
        "配置文件路径（application.yaml）",
        value=default_config_path,
    )

    # 当用户切换配置文件时，要求重新建库
    runner_cfg = st.session_state.get("runner_config_path")
    if runner_cfg is not None and runner_cfg != config_path:
        st.session_state["db_ready"] = False

    if st.sidebar.button("构建 / 刷新向量库"):
        try:
            with st.spinner("正在构建数据集与向量库…"):
                build_or_refresh_runner(config_path, overwrite=True)
            st.sidebar.success("向量库构建 / 刷新完成")
        except Exception as e:
            st.session_state["db_ready"] = False
            st.sidebar.error(f"构建向量库失败：{e}")

    db_ready = st.session_state.get("db_ready", False)
    if not db_ready:
        st.info(
            "请先在左侧点击“构建 / 刷新向量库”，"
            "完成本配置下的向量库初始化后，再使用下方功能。"
        )
        return

    mode = st.sidebar.radio(
        "模式选择",
        ("批量评估", "单条查看", "在线 RAG 问答"),
    )

    # ========================================================
    # 模式一：批量评估
    # ========================================================
    if mode == "批量评估":
        st.subheader("RAG 批量评估（EvalEngine + RAGAS）")

        st.markdown(
            f"当前配置文件：`{config_path}`，"
            "样本数上限由 `evaluation.sample_limit` 控制。"
        )

        if st.button("运行评估"):
            try:
                result = run_batch_evaluation(config_path=config_path)
            except Exception as e:
                st.error(f"评估过程中出现错误：{e}")
            else:
                st.session_state["eval_result"] = result
                st.session_state["eval_overall"] = result.overall
                st.session_state["eval_per_sample"] = result.per_sample
                st.session_state["eval_csv_path"] = result.csv_path

        overall = st.session_state.get("eval_overall")
        per_sample = st.session_state.get("eval_per_sample")
        csv_path = st.session_state.get("eval_csv_path")

        if overall is not None:
            st.markdown("**Overall 指标**")

            numeric_overall = {
                k: float(v)
                for k, v in overall.items()
                if isinstance(v, (int, float))
            }

            col1, col2 = st.columns([2, 3])

            with col1:
                st.write(numeric_overall)

            if numeric_overall:
                with col2:
                    df_overall = pd.DataFrame.from_dict(
                        numeric_overall,
                        orient="index",
                        columns=["score"],
                    )
                    df_overall.index.name = "metric"
                    st.bar_chart(df_overall)

        if per_sample is not None:
            st.markdown("**逐样本评分表**")

            if isinstance(per_sample, pd.DataFrame):
                df_samples = per_sample
            else:
                try:
                # noqa: E722
                    df_samples = pd.DataFrame(per_sample)
                except Exception:
                    df_samples = None

            if df_samples is not None:
                st.dataframe(df_samples, use_container_width=True)

        if csv_path:
            st.info(f"逐样本结果已写入 CSV：{csv_path}")

    # ========================================================
    # 模式二：单条查看
    # ========================================================
    elif mode == "单条查看":
        st.subheader("单条样本详情查看")

        per_sample = st.session_state.get("eval_per_sample")

        if per_sample is None:
            st.warning("尚未有评估结果，请先在“批量评估”模式中运行一次评估。")
            return

        if isinstance(per_sample, pd.DataFrame):
            df_samples = per_sample
        else:
            try:
            # noqa: E722
                df_samples = pd.DataFrame(per_sample)
            except Exception:
                st.error("逐样本结果格式异常，无法展示。")
                return

        st.markdown(f"当前已有样本数：{len(df_samples)} 条")

        idx = st.number_input(
            "选择样本索引（从 0 开始）",
            min_value=0,
            max_value=len(df_samples) - 1,
            value=0,
            step=1,
        )

        row = df_samples.iloc[int(idx)]

        if "question" in df_samples.columns:
            st.markdown("**Question**")
            st.write(row.get("question", ""))

        if "answer" in df_samples.columns:
            st.markdown("**Answer（RAG 生成）**")
            st.write(row.get("answer", ""))

        if "ground_truth" in df_samples.columns:
            st.markdown("**Ground Truth**")
            st.write(row.get("ground_truth", ""))

        if "contexts" in df_samples.columns:
            st.markdown("**Contexts（检索到的上下文）**")
            st.write(row.get("contexts", ""))

        metric_cols = [
            c
            for c in df_samples.columns
            if c not in ("question", "answer", "contexts", "ground_truth")
        ]
        if metric_cols:
            st.markdown("**该样本的各项指标**")
            st.write(row[metric_cols].to_dict())

    # ========================================================
    # 模式三：在线 RAG 问答
    # ========================================================
    else:
        st.subheader("在线 RAG 问答")

        try:
            runner = get_runner(config_path)
        except RuntimeError as e:
            st.error(str(e))
            return

        question = st.text_area(
            "输入你的问题（将通过当前配置的 RAG 链路检索与生成）：",
            height=100,
            placeholder="例如：CMRC2018 数据集主要解决什么任务？",
        )

        if st.button("发送"):
            if not question.strip():
                st.warning("问题内容不能为空。")
                return

            with st.spinner("正在通过 RAG 链路生成答案…"):
                out: Dict[str, Any] = runner.invoke(question)

            answer = out.get("answer") or out.get("generation", "")
            contexts = out.get("contexts", [])

            st.markdown("**Answer**")
            st.write(answer)

            if contexts:
                st.markdown("**检索到的上下文（前若干条）**")
                for i, ctx in enumerate(contexts[:3]):
                    st.markdown(f"Context {i + 1}")
                    st.write(str(ctx))

if __name__ == "__main__":
    main()

