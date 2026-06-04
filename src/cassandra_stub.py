"""
In-memory Cassandra stub for sandbox / CI runs where Cassandra is unavailable.
Activated when CASSANDRA_STUB=1 is set in the environment.
Stores rows in a dict; supports the same .execute() interface as cassandra-driver.
"""
import threading
from collections import defaultdict


class StubSession:
    def __init__(self):
        self._store: dict[str, list[dict]] = defaultdict(list)
        self._lock = threading.Lock()

    def execute(self, query: str, params: tuple = ()):
        # No-op for DDL (CREATE TABLE, CREATE KEYSPACE)
        q = query.strip().upper()
        if q.startswith("CREATE") or q.startswith("ALTER") or q.startswith("DROP"):
            return
        # For INSERT, store params as a tuple (just for measurement completeness)
        if q.startswith("INSERT") and params:
            table = "traces"
            with self._lock:
                self._store[table].append(params)

    def __len__(self):
        return sum(len(v) for v in self._store.values())


_stub_session: StubSession | None = None


def get_stub_session() -> StubSession:
    global _stub_session
    if _stub_session is None:
        _stub_session = StubSession()
    return _stub_session
