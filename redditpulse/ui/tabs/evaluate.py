"""Evaluate tab: benchmark sentiment models against manual labels."""

import pandas as pd
import streamlit as st

from redditpulse import services


def render(topic: str) -> None:
    st.subheader(f"Model Evaluation: {topic}")
    st.caption("Compare sentiment model predictions against your manual ground-truth labels.")

    ev1, ev2 = st.columns([2, 1])
    with ev1:
        model_choice = st.selectbox("Model to evaluate", ["vader", "textblob", "claude"], key="eval_model")
    with ev2:
        run_eval = st.button("Run Evaluation", use_container_width=True, type="primary")

    if run_eval:
        try:
            result = services.evaluate_sentiment(topic, model=model_choice)
            st.session_state["eval_result"] = result
        except services.TopicNotFoundError as e:
            st.error(str(e))
        except services.NoCommentsError as e:
            st.warning(str(e))
        except ImportError as e:
            st.error(str(e))

    eval_result = st.session_state.get("eval_result")
    if not eval_result:
        return

    st.markdown("---")
    st.markdown(f"**Model:** `{eval_result['model']}` · **Labeled comments:** {eval_result['total_labeled']}")

    acc_col, _ = st.columns([1, 3])
    acc_col.metric("Accuracy", f"{eval_result['accuracy']:.1%}")

    st.subheader("Per-class Metrics")
    pc = eval_result["per_class"]
    pc_df = pd.DataFrame([
        {"Class": lbl, "Precision": v["precision"], "Recall": v["recall"],
         "F1": v["f1"], "Support": v["support"]}
        for lbl, v in pc.items()
    ])
    st.dataframe(pc_df, use_container_width=True, hide_index=True)

    st.subheader("Confusion Matrix (rows = Ground Truth, cols = Predicted)")
    order = eval_result["labels_order"]
    cm = eval_result["confusion_matrix"]
    cm_df = pd.DataFrame(
        [[cm[g][p] for p in order] for g in order],
        index=[f"GT: {g}" for g in order],
        columns=[f"Pred: {p}" for p in order],
    )
    st.dataframe(cm_df, use_container_width=True)
