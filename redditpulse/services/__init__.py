"""Service layer: the public API used by the CLI, GUI and showcase builder.

Each service function owns its DB session and returns plain dicts, so callers
never touch SQL, fetchers or the Anthropic client directly.
"""

from ..exceptions import (  # noqa: F401
    NoAnalysisError, NoCommentsError, RedditPulseError, TopicNotFoundError,
)
from .topics import (  # noqa: F401
    delete_topic, generate_keywords, generate_subreddits, get_showcase_config,
    get_topic_summary, list_topics, next_available_topic_name, set_showcase_config,
    set_topic_note,
)
from .search import search_topic  # noqa: F401
from .analyze import (  # noqa: F401
    analyze_topic, browse_comments, evaluate_sentiment, export_analysis,
    get_comments_for_labeling, get_sentiment_trends, label_comment,
)
from .data import (  # noqa: F401
    delete_fetch_run, get_data_overview, list_fetch_runs, trim_comments,
    validate_topic_data,
)
