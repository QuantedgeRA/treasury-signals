"""ScanState — per-scan-cycle data container threaded through phase functions."""

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ScanState:
    """Mutable container for per-scan data. Created at the top of each scan
    cycle; phases read and mutate it; post-scan code consumes the final state.

    Attributes are namespaced by the phase that produces them. New cross-phase
    data should be added here, not as ad-hoc locals threaded through arguments.
    """

    # Always set at construction
    scan_number: int
    morning: bool
    accounts: list = field(default_factory=list)

    # Phase 1 outputs (tweet fetch)
    tweets_new: int = 0
    tweets_skipped: int = 0

    # Phase 2 outputs (classification)
    signals: list = field(default_factory=list)
    alerts_sent: int = 0

    # Phase 5 outputs (correlation engine + pattern matching)
    correlation: dict = field(default_factory=dict)
    pattern_match: dict = field(default_factory=lambda: {
        "score": 0, "matched_count": 0, "total_patterns": 0,
        "matching_patterns": [], "narrative": "",
    })
    fg_value: int = 50
    btc_weekly: float = 0

    # Phase 8 outputs (purchase + sale detection)
    detected: list = field(default_factory=list)
