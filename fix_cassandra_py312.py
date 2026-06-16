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

# Find the line with DependencyException and show context
lines = content.splitlines()
dep_lines = [(i, l) for i, l in enumerate(lines) if "DependencyException" in l and "raise" in l]

if not dep_lines:
    print("ERROR: Could not find 'raise DependencyException' in cluster.py.")
    sys.exit(1)

# Show what we found so we can diagnose
line_no, line_text = dep_lines[0]
print(f"Found at line {line_no + 1}: {line_text.strip()}")
print("Context (±5 lines):")
for i in range(max(0, line_no - 5), min(len(lines), line_no + 6)):
    prefix = ">>>" if i == line_no else "   "
    print(f"  {prefix} {i+1:4d}: {lines[i]}")

# Try multiple known patterns across driver versions
PATCHES = [
    # Pattern A: _NOT_SET sentinel (common in 3.28+)
    (
        "    if DefaultConnection is _NOT_SET:\n"
        "        raise DependencyException",
        (
            f"    {MARKER}\n"
            "    if DefaultConnection is _NOT_SET:\n"
            "        try:\n"
            "            from cassandra.io.asyncioreactor import AsyncioConnection\n"
            "            DefaultConnection = AsyncioConnection\n"
            "        except Exception:\n"
            "            pass\n"
            "    if DefaultConnection is _NOT_SET:\n"
            "        raise DependencyException"
        ),
    ),
    # Pattern B: None check (older style)
    (
        "    if not DefaultConnection:\n"
        "        raise DependencyException",
        (
            f"    {MARKER}\n"
            "    if not DefaultConnection:\n"
            "        try:\n"
            "            from cassandra.io.asyncioreactor import AsyncioConnection\n"
            "            DefaultConnection = AsyncioConnection\n"
            "        except Exception:\n"
            "            pass\n"
            "    if not DefaultConnection:\n"
            "        raise DependencyException"
        ),
    ),
    # Pattern C: direct raise without if guard (minimal style)
    (
        "raise DependencyException(\"Unable to load a default connection class\"",
        (
            f"{MARKER}\n"
            "try:\n"
            "    from cassandra.io.asyncioreactor import AsyncioConnection\n"
            "    DefaultConnection = AsyncioConnection\n"
            "except Exception:\n"
            "    pass\n"
            "if not DefaultConnection:\n"
            "    raise DependencyException(\"Unable to load a default connection class\""
        ),
    ),
]

patched = False
for old, new in PATCHES:
    if old in content:
        content = content.replace(old, new, 1)
        cluster_py.write_text(content, encoding="utf-8")
        print(f"\nPatched successfully: {cluster_py}")
        patched = True
        break

if not patched:
    # Last resort: show the exact lines around the raise so we can fix manually
    print("\nCould not apply automatic patch. Paste the 10 lines above to get a manual fix.")
    sys.exit(1)

print("You can now use cassandra-driver on Python 3.12 without libev or asyncore.")
