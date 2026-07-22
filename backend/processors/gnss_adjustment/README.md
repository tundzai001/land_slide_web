# GNSS adjustment package

All baseline-network adjustment code lives in this package:

- `models.py`: network, point, baseline, and result models.
- `solver.py`: weighted least-squares network solver.
- `transforms.py`: coordinate and covariance transformations.
- `runtime.py`: AGRICA parsing and direct adjustment runtime.
- `round_robin.py`: receiver rotation and fixed-base collection workflow.
- `statistics.py`: stability, effective sample size, and covariance accumulation.
- `geometry.py`: coordinate, graph, baseline aggregation, and loop helpers.
- `session.py`: collected-observation and receiver-command state.
- `reporting.py`: Excel, JSON audit, and text report generation.

The files one directory above named `round_robin_manager.py` and
`gnss_adjustment_runtime.py` are compatibility aliases only. New code must
import from `processors.gnss_adjustment`.
