from sqlalchemy import URL, Engine, create_engine


def create_database_engine(url: URL) -> Engine:
    """Engine used by the API and the worker, with every wait bounded."""
    return create_engine(
        url,
        pool_pre_ping=True,
        pool_timeout=5,  # seconds waiting for a free pooled connection
        connect_args={
            "connect_timeout": 3,  # seconds to establish a connection
            # ms of unacknowledged data before the socket is dropped: a server
            # that stops answering cannot hang a request forever.
            "tcp_user_timeout": 5000,
            # Server-side bounds for slow queries and lock waits (each FETCH
            # of a streamed export is its own statement). A server that is
            # fully frozen yet still ACKs TCP is not bounded here: psycopg has
            # no client-side per-query timeout (documented).
            "options": "-c statement_timeout=10000 -c lock_timeout=5000",
        },
    )
