"""Run pure tests and independent mocked-API/integration suites in isolation."""
from pathlib import Path
import subprocess
import sys

root = Path(__file__).resolve().parent
subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"], cwd=root, check=True)
for test in sorted((root / "tests" / "independent").glob("test_*.py")):
    subprocess.run([sys.executable, str(test)], cwd=root, check=True)
