"""
One-time patch: add asyncio reactor as fallback in cassandra/cluster.py.

cassandra-driver 3.30.0 on Python 3.12 + Windows fails because:
  - libev C extension not available on Windows
  - asyncore removed in Python 3.12
  - asyncio reactor needs WindowsSelectorEventLoopPolicy on Windows

Run once after installing cassandra-driver:
    python fix_cassandra_py312.py

To undo (if something goes wrong):
    pip install --force-reinstall cassandra-driver
"""
import pathlib
import sys

import cassandra

cluster_py = pathlib.Path(cassandra.__file__).parent / "cluster.py"
content = cluster_py.read_text(encoding="utf-8")

MARKER = "# _PY312_ASYNCIO_PATCH"

if MARKER in content:
    print(f"Already patched: {cluster_py}")
    sys.exit(0)

# Target pattern (Apache cassandra-driver 3.30.0):
#
#   conn_fns = (_try_gevent_import, _try_eventlet_import, _try_libev_import, _try_asyncore_import)
#   (conn_class, excs) = reduce(_connection_reduce_fn, conn_fns, (None,[]))
#   if not conn_class:
#       raise DependencyException("Unable to load a default connection class", excs)
#   DefaultConnection = conn_class
#
# Fix: catch the DependencyException and fall back to asyncio with
# WindowsSelectorEventLoopPolicy (required on Windows for add_reader support).

old = (
    "conn_fns = (_try_gevent_import, _try_eventlet_import, _try_libev_import, _try_asyncore_import)\n"
    "(conn_class, excs) = reduce(_connection_reduce_fn, conn_fns, (None,[]))\n"
    "if not conn_class:\n"
    "    raise DependencyException(\"Unable to load a default connection class\", excs)\n"
    "DefaultConnection = conn_class"
)

new = (
    f"{MARKER}\n"
    "conn_fns = (_try_gevent_import, _try_eventlet_import, _try_libev_import, _try_asyncore_import)\n"
    "(conn_class, excs) = reduce(_connection_reduce_fn, conn_fns, (None,[]))\n"
    "if not conn_class:\n"
    "    try:\n"
    "        import asyncio as _asyncio, sys as _sys\n"
    "        if _sys.platform == 'win32':\n"
    "            _asyncio.set_event_loop_policy(_asyncio.WindowsSelectorEventLoopPolicy())\n"
    "        _asyncio.set_event_loop(_asyncio.new_event_loop())\n"
    "        from cassandra.io.asyncioreactor import AsyncioConnection\n"
    "        conn_class = AsyncioConnection\n"
    "    except Exception as _e:\n"
    "        raise DependencyException(\"Unable to load a default connection class\", excs) from _e\n"
    "DefaultConnection = conn_class"
)

if old in content:
    content = content.replace(old, new, 1)
    cluster_py.write_text(content, encoding="utf-8")
    print(f"Patched successfully: {cluster_py}")
    print("asyncio reactor with WindowsSelectorEventLoopPolicy added for Python 3.12 + Windows.")
    sys.exit(0)

# Could not find exact pattern — show context for diagnosis
lines = content.splitlines()
dep_lines = [(i, l) for i, l in enumerate(lines) if "DependencyException" in l and "raise" in l]
if dep_lines:
    line_no, _ = dep_lines[0]
    print("Could not find expected pattern. Context:")
    for i in range(max(0, line_no - 8), min(len(lines), line_no + 4)):
        prefix = ">>>" if i == line_no else "   "
        print(f"  {prefix} {i+1:4d}: {lines[i]}")
print("\nShare the output above to get a manual fix.")
sys.exit(1)
