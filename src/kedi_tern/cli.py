"""JSON protocol: UTF-8 source on stdin, one highlight response on stdout."""

from __future__ import annotations

import json
import sys

from kedi_tern.highlight import MAX_SOURCE_BYTES, highlight


def main() -> int:
    try:
        raw = sys.stdin.buffer.read(MAX_SOURCE_BYTES + 1)
        if len(raw) > MAX_SOURCE_BYTES:
            raise ValueError("Source exceeds the 1 MiB viewer limit")
        response = highlight(raw.decode("utf-8"))
    except (ValueError, RuntimeError) as exc:
        print(f"kedi-tern: {exc}", file=sys.stderr)
        return 1
    json.dump(response, sys.stdout, ensure_ascii=True, separators=(",", ":"))
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
