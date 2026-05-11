"""scheduler — owns the scan loop, phases, and the singleton CorrelationEngine.

The engine instance lives here (not in main.py) so phases.py and helpers.py
can import it without creating a circular dependency through main.

Usage from main.py:
    from treasury_signals.scheduler import engine
    from treasury_signals.scheduler.state import ScanState
    from treasury_signals.scheduler.phases import (
        phase_1_tweets, phase_2_classify, ..., phase_9_regulatory,
    )
"""

from treasury_signals.pipelines.correlation_engine import CorrelationEngineV2

# Singleton CorrelationEngine — shared across phases for the lifetime of the
# process. Phases append signals via engine.add_*; phase_5_correlation reads
# the accumulated state.
engine = CorrelationEngineV2()
