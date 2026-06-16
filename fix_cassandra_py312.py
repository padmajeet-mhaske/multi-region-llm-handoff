"""
One-time patch: add asyncio reactor as fallback in cassandra/cluster.py.

cassandra-driver 3.29/3.30 on Python 3.12 raises DependencyException because
asyncore was removed in Python 3.12 and libev is rarely installed on Windows.
The driver does not auto-fall back to asyncio. This script patches the
installed cluster.py to add asyncio as a third fallback.

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

# The exact block we're inserting before the DependencyException raise.
# Pattern exists in both 3.29 and 3.30 Apache releases.
old = (
    "    if DefaultConnection is _NOT_SET:\n"
    "        raise DependencyException"
)

new = (
    f"    {MARKER}\n"
    "    if DefaultConnection is _NOT_SET:\n"
    "        try:\n"
    "            from cassandra.io.asyncioreactor import AsyncioConnection\n"
    "            DefaultConnection = AsyncioConnection\n"
    "        except Exception:\n"
    "            pass\n"
    "    if DefaultConnection is _NOT_SET:\n"
    "        raise DependencyException"
)

if old not in content:
    print("ERROR: Could not find the expected pattern in cluster.py.")
    print("       The driver version may have changed. Manual fix needed.")
    print(f"       File: {cluster_py}")
    sys.exit(1)

patched = content.replace(old, new, 1)
cluster_py.write_text(patched, encoding="utf-8")
print(f"Patched successfully: {cluster_py}")
print("You can now use cassandra-driver on Python 3.12 without libev or asyncore.")
