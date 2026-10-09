"""Source-checkout entry point, independent of the process working directory."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

try:
    from kedi_tern.cli import main
except ImportError as exc:
    print(
        f"Kedi highlighter dependencies are missing: {exc}. "
        "Run uv sync --locked --no-dev in the plugin directory.",
        file=sys.stderr,
    )
    raise SystemExit(1) from None

if __name__ == "__main__":
    raise SystemExit(main())
