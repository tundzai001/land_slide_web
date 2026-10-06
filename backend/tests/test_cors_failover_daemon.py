"""Transient CORS failures must retry without flooding the production console."""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app import main


def test_failover_retries_back_off_and_recovery_restores_normal_polling():
    project = SimpleNamespace(id=3, gnss_clusters=[{'backup_base_station': 'backup'}])
    rows = SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: [project]))
    delays = []

    async def sleep(delay):
        delays.append(delay)
        if len(delays) == 4:
            raise asyncio.CancelledError

    with patch.object(main, 'ConfigSessionLocal') as session, \
            patch.object(main.config.settings, 'GNSS_CORS_FAILOVER_POLL_SECONDS', 2), \
            patch.object(main.mqtt_service.round_robin_manager, 'reconcile_cors_failover_pairs',
                         new=AsyncMock(side_effect=[RuntimeError('CORS API HTTP 502: upstream')] * 3 + [[]])), \
            patch.object(main.asyncio, 'sleep', side_effect=sleep), \
            patch.object(main.time, 'monotonic', return_value=10), \
            patch.object(main.logger, 'warning') as warning, \
            patch.object(main.logger, 'info') as info:
        session.return_value.__aenter__.return_value.execute = AsyncMock(return_value=rows)
        try:
            asyncio.run(main.run_cors_fixed_base_failover_daemon())
        except asyncio.CancelledError:
            pass
        assert delays == [4, 8, 16, 2]
        warning.assert_called_once()
        info.assert_any_call('CORS fixed-base failover connection recovered')
