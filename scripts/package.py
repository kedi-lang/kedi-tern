"""Build the complete extension ZIP without caches or virtual environments."""

from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

ROOT = Path(__file__).resolve().parents[1]
VERSION = "0.2.0"
FILES = [
    "plugin.toml",
    "host.luau",
    "window.luau",
    "pyproject.toml",
    "uv.lock",
    "README.md",
    "python/highlight.py",
    "src/kedi_tern/__init__.py",
    "src/kedi_tern/highlight.py",
    "src/kedi_tern/cli.py",
    "examples/hello.kedi",
    "examples/python.kedi",
    "scripts/package.py",
    "tests/test_highlight.py",
]


def main() -> None:
    destination = ROOT / "dist" / f"kedi-tern-{VERSION}.zip"
    destination.parent.mkdir(exist_ok=True)
    # Check the allowlist before opening the archive, so failures leave no partial ZIP.
    for relative in FILES:
        if not (ROOT / relative).is_file():
            raise FileNotFoundError(relative)
    with ZipFile(destination, "w", compression=ZIP_DEFLATED) as archive:
        for relative in FILES:
            archive.write(ROOT / relative, f"kedi-tern/{relative}")
    print(destination)


if __name__ == "__main__":
    main()
