# GNSS monitoring isolation and recovery

The locked `GNSSOrigin` coordinates, rotation matrix and tracking offset remain unchanged during adjustment and monitoring recovery.

## Adjustment isolation

GGA monitoring is paused for the affected project/stations during `STARTING`, `COLLECTING_BASELINE`, `FREE_NETWORK` and `PAUSED`. A retained seed topology snapshot also pauses monitoring while the correction topology is being changed or restoration has failed, including before the public adjustment phase exists. Scheduler sessions retain their real project ID before handover.

AGRICA adjustment ingestion continues. Monitoring resumes after restoration releases the topology snapshot and the active adjustment phase ends.

## Recovery from a stale sample reference

A stale accepted sample can keep rejecting measurements that have already returned to the locked origin. Recovery rebuilds the measurement and velocity windows using the actual FIXED samples, subject to all of these conditions:

- The accepted sample is over 60 seconds old and outside the locked-origin return bounds.
- At least six recent FIXED samples pass the existing satellite/HDOP and stability gates.
- Every candidate lies within 0.03 m horizontally and 0.05 m vertically of the original, uncompensated locked origin.
- Candidate gaps remain within `GnssIntegrity.origin_max_gap_s` (default 2 seconds).
- The return remains qualified for 60 seconds. Any failed return check restarts the timer; restart also restarts the timer.

The sample window retains measured ENU values. Recovery does not write a new origin or tracking offset. Velocity/displacement readiness resets and the status remains `WARMING_UP` until normal measurement windows are ready. Historical peak displacement remains intact. Samples outside the return bounds remain quarantined; the existing verified-reference compensation gates still apply independently.

## Console behavior

GNSS quarantine emits a warning on a new state and at most one reminder per five minutes for an unchanged state, using the server monotonic clock. Status updates, rejected-sample counters, raw anomaly persistence and alerts continue independently of console logging.

CORS integration retries failed reconciliation with exponential backoff up to 60 seconds (or the configured polling period when longer). Repeated identical errors log at most every five minutes; recovery returns to normal polling and emits an informational message.

## WebSocket runtime

`server.py` selects Uvicorn's `websockets-sansio` protocol. `backend/requirements.txt` includes its pinned `websockets` dependency so server deployments support WebSocket upgrades.

## Verification

Run:

```sh
PYTHONPATH=backend python -m pytest backend/tests/test_gnss_integrity.py backend/tests/test_ntrip_round_robin_transport.py backend/tests/test_cors_failover_daemon.py backend/tests/test_logging_config.py -q
```

On deployment, compare original `GNSSOrigin` records against the pre-deployment snapshot, observe fresh sensor status and runtime checkpoints, and test an authenticated WebSocket ping/pong. A quiet console alone does not establish successful monitoring recovery.
