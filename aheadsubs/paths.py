import os
from pathlib import Path


def user_data_directory():
    local = Path(os.environ["LOCALAPPDATA"])
    current = local / "AheadSubs"
    legacy = local / "Subtitle Relay"
    if not current.exists() and legacy.is_dir():
        return legacy
    return current
