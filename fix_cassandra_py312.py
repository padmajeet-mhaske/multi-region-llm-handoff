"""
One-time patch: add asyncio reactor as fallback in cassandra/cluster.py.

cassandra-driver 3.29/3.30 on Python 3.12 raises DependencyException because
asyncore was removed in Python 3.12 and libev is rarely installed on Windows.
This script patches the installed cluster.py to add asyncio as a fallback.

Run once:
    python fix_cassandra_py312.py
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

# Exact pattern seen in Apache cassandra-driver 3.30.0:
#
#   conn_fns = (_try_gevent_import, _try_eventlet_import, _try_libev_import, _try_asyncore_import)
#   (conn_class, excs) = reduce(_connection_reduce_fn, conn_fns, (None,[]))
#   if not conn_class:
#       raise DependencyException("Unable to load a default connection class", excs)
#   DefaultConnection = conn_class
#
# Fix: inject asyncio as a 5th fallback into conn_fns so conn_class gets set.

old = (
    "conn_fns = (_try_gevent_import, _try_eventlet_import, _try_libev_import, _try_asyncore_import)\n"
    "(conn_class, excs) = reduce(_connection_reduce_fn, conn_fns, (None,[]))\n"
    "if not conn_class:\n"
    "    raise DependencyException(\"Unable to load a default connection class\", excs)\n"
    "DefaultConnection = conn_class"
)

new = (
    f"{MARKER}\n"
    "def _try_asyncio_import():\n"
    "    try:\n"
    "        from cassandra.io.asyncioreactor import AsyncioConnection\n"
    "        return AsyncioConnection\n"
    "    except Exception as e:\n"
    "        return None, e\n"
    "\n"
    "conn_fns = (_try_gevent_import, _try_eventlet_import, _try_libev_import, _try_asyncore_import, _try_asyncio_import)\n"
    "(conn_class, excs) = reduce(_connection_reduce_fn, conn_fns, (None,[]))\n"
    "if not conn_class:\n"
    "    raise DependencyException(\"Unable to load a default connection class\", excs)\n"
    "DefaultConnection = conn_class"
)

if old in content:
    content = content.replace(old, new, 1)
    cluster_py.write_text(content, encoding="utf-8")
    print(f"Patched successfully: {cluster_py}")
    print("asyncio reactor added as fallback connection class for Python 3.12.")
    sys.exit(0)

# Fallback: generic pattern
old2 = 'raise DependencyException("Unable to load a default connection class", excs)\nDefaultConnection = conn_class'
new2 = (
    f"{MARKER}\n"
    "try:\n"
    "    from cassandra.io.asyncioreactor import AsyncioConnection\n"
    "    conn_class = conn_class or AsyncioConnection\n"
    "except Exception:\n"
    "    pass\n"
    'if not conn_class:\n'
    '    raise DependencyException("Unable to load a default connection class", excs)\n'
    "DefaultConnection = conn_class"
)
if old2 in content:
    content = content.replace(old2, new2, 1)
    cluster_py.write_text(content, encoding="utf-8")
    print(f"Patched successfully (fallback pattern): {cluster_py}")
    sys.exit(0)

# Show context for manual diagnosis
lines = content.splitlines()
dep_lines = [(i, l) for i, l in enumerate(lines) if "DependencyException" in l and "raise" in l]
if dep_lines:
    line_no, _ = dep_lines[0]
    print("Could not apply patch. Context around DependencyException:")
    for i in range(max(0, line_no - 8), min(len(lines), line_no + 4)):
        prefix = ">>>" if i == line_no else "   "
        print(f"  {prefix} {i+1:4d}: {lines[i]}")
print("\nPlease share the output above.")
sys.exit(1)
