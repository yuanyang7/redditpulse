"""Shared Altair chart builders."""

import altair as alt
import pandas as pd


def emotions_chart(df: pd.DataFrame) -> alt.Chart:
    """Horizontal bar chart of emotions ranked by prevalence."""
    return alt.Chart(df).mark_bar(color="#FF6B4A").encode(
        x=alt.X("prevalence:Q", title="Prevalence"),
        y=alt.Y("emotion:N", title="", sort="-x"),
        tooltip=["emotion", "prevalence"],
    )


def breakdown_chart(df: pd.DataFrame, dimension: str) -> alt.Chart:
    """Horizontal bar chart of a topic's category breakdown by percentage."""
    return alt.Chart(df).mark_bar(color="#7C5CFF").encode(
        x=alt.X("percentage:Q", title="%"),
        y=alt.Y("category:N", title="", sort="-x"),
        tooltip=["category", "percentage"],
    ).properties(title=dimension)


def themes_chart(df: pd.DataFrame) -> alt.Chart:
    """Horizontal bar chart of themes by mention count."""
    return alt.Chart(df).mark_bar(color="#2D5BFF").encode(
        x=alt.X("count:Q", title="Mentions"),
        y=alt.Y("theme:N", title="", sort="-x"),
        tooltip=["theme", "count", "summary"],
    )
