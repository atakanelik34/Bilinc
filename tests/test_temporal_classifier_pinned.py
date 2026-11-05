"""Time-window routing must not change how normal recall classifies queries.

``classify_temporal_query`` matches substrings ("date" inside "updated",
"time" inside "timeline"). Fixing that would hand the temporal ranking signal
to queries that get none today, so it stays as it is; routed queries never
reach it. These outputs are pinned on purpose.
"""
import pytest

from bilinc.core.temporal import classify_temporal_query


@pytest.mark.parametrize(
    "query,expected",
    [
        ("updated after the migration", "when"),
        ("project timeline", "when"),
        ("daytona deck", "when"),
        ("when did we ship 2.6.1", "when"),
        ("what changed today", "when"),
        ("since Monday", "when"),
        ("then and now", "after"),
        ("last version of the deck", "after"),
        ("bugünün güncellemeleri", None),
        ("dünkü kararlar", None),
        ("pricing plan", None),
    ],
)
def test_classifier_outputs_are_unchanged(query, expected):
    assert classify_temporal_query(query) == expected
