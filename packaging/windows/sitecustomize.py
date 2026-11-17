"""Private runtime configuration embedded in Windows distributions only."""
import os
from pathlib import Path
import sys


app = Path(sys.base_prefix).parent
bundle_bin = str(app / "bin")
if bundle_bin not in os.environ.get("PATH", "").split(os.pathsep):
    os.environ["PATH"] = os.pathsep.join((bundle_bin, os.environ.get("PATH", "")))
sys.path.insert(0, str(app))
