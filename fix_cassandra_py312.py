"""
[SUPERSEDED] cassandra-driver Python 3.12 / Windows compatibility fix.

The fix is now built directly into src/handoff_runner.py:
  - asyncore + asynchat are stubbed in sys.modules before any cassandra import
  - WindowsSelectorEventLoopPolicy is set on win32 + Python 3.12
  - AsyncioConnection is imported and passed as connection_class to Cluster()

You no longer need to run this script.

If you previously ran an older version of this script and want to revert the
patch from cassandra/cluster.py:
    pip install --force-reinstall cassandra-driver

To verify the fix works (Python 3.12 + Windows, real Cassandra running):
    set CASSANDRA_STUB=
    python -c "from src.handoff_runner import connect_cassandra; s = connect_cassandra(); print('OK', s)"
"""
import sys

print("This script is no longer needed.")
print("The asyncore stub and asyncio reactor setup are now built into")
print("src/handoff_runner.py and run automatically on Python 3.12 + Windows.")
print()
print("To revert any previous cassandra/cluster.py patch (if needed):")
print("    pip install --force-reinstall cassandra-driver")
sys.exit(0)
