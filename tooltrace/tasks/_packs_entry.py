"""Entry-point target for the bundled task packs.

Exposed under the ``tooltrace.task_packs`` entry-point group so pack
discovery works through the same plugin mechanism third-party task packs
use. :func:`tooltrace.tasks.loader.plugin_pack_dirs` accepts a ``Path`` or an
object exposing a ``pack_dir`` attribute.
"""

from __future__ import annotations

from pathlib import Path

builtin: Path = Path(__file__).resolve().parent / "packs"
