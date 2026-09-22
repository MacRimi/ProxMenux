"""The downloaded OCI images an installation was created from: the container
does not need them once it exists, so the user may delete them."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from . import console
from .i18n import translate

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _cache(command: str, vmids: list[int]) -> dict[str, Any] | None:
    result = subprocess.run([sys.executable, str(PROJECT_ROOT / "remote" / "oci_image_cache.py"), command,
                             *map(str, vmids)], capture_output=True, text=True, check=False)
    try:
        return json.loads(result.stdout) if result.returncode == 0 else None
    except ValueError:
        return None


def size_text(size: int) -> str:
    return f"{size / 1024**3:.1f} GB" if size >= 1024**3 else f"{max(1, round(size / 1024**2))} MB"


def offer_removal(ui, vmids: list[int]) -> tuple[bool, str | None]:
    """Asks whether to delete the images of these installations. Returns whether
    the question was shown and the line to report when they were deleted."""
    listed = _cache("list", vmids)
    archives = (listed or {}).get("archives") or []
    if not archives:
        return False, None
    total = size_text(sum(item["size"] for item in archives))
    if len(archives) == 1:
        text = (f"{translate('The container was created from a downloaded OCI image')} ({total}). "
                f"{translate('The container does not need it any more; an update downloads the new version when there is one.')}"
                f"\n\n{translate('Delete the image to free the space?')}")
    else:
        text = (f"{translate('The containers were created from downloaded OCI images')} ({len(archives)}, {total}). "
                f"{translate('The containers do not need them any more; an update downloads the new versions when there are any.')}"
                f"\n\n{translate('Delete the images to free the space?')}")
    if not console.ask_yes_no(text, True):
        return True, None
    removed = _cache("remove", vmids)
    if not removed or not removed.get("freed"):
        return True, None
    return True, f"{translate('Downloaded OCI images deleted:')} {size_text(removed['freed'])}"
