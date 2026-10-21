"""Work around asyncpg 0.31.0 TLS negotiation races without changing SSL policy."""

import logging

import asyncpg
from asyncpg import connect_utils

logger = logging.getLogger(__name__)


def _retrieve_negotiation_exception(future):
    # create_connection can fail before its caller gets the protocol. In that
    # case nobody awaits on_data. Retrieving the exception still lets normal
    # awaiters receive it, but prevents an orphaned Future warning.
    if not future.cancelled():
        future.exception()


class _SafeTLSUpgradeProto(connect_utils.TLSUpgradeProto):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.on_data.add_done_callback(_retrieve_negotiation_exception)

    def data_received(self, data):
        # Backport the upstream done() guard: Windows may deliver an SSL reply
        # after the connection timeout has cancelled the negotiation Future.
        # https://github.com/MagicStack/asyncpg/blob/master/asyncpg/connect_utils.py
        if not self.on_data.done():
            super().data_received(data)


def install_asyncpg_tls_fix():
    # Private driver hook, restricted to the version pinned in requirements.
    # Reassess/remove this compatibility patch when upgrading asyncpg.
    if asyncpg.__version__ == "0.31.0":
        connect_utils.TLSUpgradeProto = _SafeTLSUpgradeProto
        logger.info("asyncpg %s: TLS negotiation compatibility fix enabled", asyncpg.__version__)
    else:
        logger.warning(
            "asyncpg %s differs from pinned 0.31.0; TLS compatibility fix is not installed. "
            "Install backend/requirements.txt using the server's Python interpreter.",
            asyncpg.__version__,
        )
