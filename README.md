# Kedi for Tern

A read-only `.kedi` viewer for Tern, using `tree-sitter-kedi` and `tree-sitter-python`.
The extension runs a Python helper and displays its UTF-16 decorations in a
native Tern editor. Source code, including embedded Python, is never executed.

## Install from a checkout

Requires Tern, Python 3.10+, and [uv](https://docs.astral.sh/uv/).

```sh
uv sync --locked --no-dev
tern plugin link .
tern open examples/hello.kedi
```

The plugin uses `.venv/bin/python` (`.venv/Scripts/python.exe` on Windows) in
its own directory. No activated shell is necessary. To use an existing
environment, set `TERN_KEDI_PYTHON` to its absolute Python executable path in
Tern's environment, then restart Tern. That environment needs the dependencies
listed in `pyproject.toml`.

For a copied installation, run `tern plugin install /path/to/kedi-tern`, then
run `uv sync --locked --no-dev` **inside the installed plugin directory**.
Do not move or copy an existing virtual environment. On remote hosts, install
the plugin and its Python environment on the host that owns the files as well.

## Use

Open a `.kedi` file normally, or choose **Open with → Kedi**. Extension matching
is case-insensitive. Tern keeps requested split/tab placement. Opens specifying
a line or column stay in Tern's built-in file viewer. Tern's own Files previews,
git/board opens, and state restore do not pass through the open route.

The viewer is read-only and has a Reload button (`r` also reloads). It does not watch the file.
It shows plain source while highlighting runs; helper failures leave the source
visible with a readable error. Files must be UTF-8, at most 1 MiB, and at most
20,000 lines. Embedded Python is highlighted in fenced blocks, fenced assignment
and return values, inline backticks, defaults, and Python type annotations.
Editing and LSP support are not included.

Try `tern open examples/python.kedi` for a mixed-language example. To update a
linked checkout, run `uv sync --locked --no-dev`, then click **Reload** in the
viewer. No relinking is needed.

Kedi syntax follows the installed grammar. In particular, `> instructions:` is
supported; the legacy `> system:` spelling is not translated or accepted. A
syntax warning means either the Kedi parser or an injected Python parser found
an error.

## Develop and verify

```sh
uv sync --locked
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run kedi-tern-highlight < examples/hello.kedi
```

`plugin.toml`, `host.luau`, and `window.luau` are the Tern extension. The Python
package lives in `src/kedi_tern`; `python/highlight.py` launches it directly from
a checkout, so it works even when Tern sets another working directory.

Capture names use exact mappings followed by dotted-parent fallback. Private
query captures are ignored for coloring, while query predicates still run.
Python regions come from the packaged `injections.scm`; each region is parsed
independently with `tree-sitter-python` and its packaged highlight query. Python
colors override the surrounding Kedi string capture, including a neutral color
for uncaptured punctuation and whitespace. F-string expressions are highlighted
as Python. Indentation and the displayed source are preserved. CRLF is normalized
only for parsing, then mapped back to the original document before UTF-16 conversion.

Within each language layer, overlaps resolve by explicit `priority`, narrower range, later query pattern,
then later capture declaration. Adjacent equal colors merge. UTF-8 byte offsets
are converted to end-exclusive UTF-16 units, including surrogate pairs.

Tern's `syntax*` span tokens use the active theme's semantic colors in plugin
views; their colors may differ from Tern's built-in code highlighter.

Version 0.2.0 was checked with Python 3.10 and 3.14 (23 tests on each), Ruff,
and Tern 0.6.2 on macOS. Tests include Python fences, inline expressions,
f-strings, method calls, LF/CRLF, and Unicode offsets. Live checks covered
Python token colors and the final line-number gutter. Version 0.1 checks also covered uppercase file
extensions, tab placement, reloading changed files, missing-file errors, and
line/column opens falling back to Tern. The ZIP was also installed and run from
a fresh directory with only its locked runtime dependencies.

## Package

```sh
uv build
uv run python scripts/package.py
```

`uv build` produces the Python helper wheel and a source distribution. The ZIP
produced by `scripts/package.py` is the complete Tern extension, excluding
virtual environments, caches, and development outputs. Unzip it, run
`uv sync --locked --no-dev` in that folder, then `tern plugin link .`.

The standalone Python wheel provides `kedi-tern-highlight`; it does not install
the Tern extension. No package publication or repository push is automatic.

## SDK references

- [File routing and Open with](https://docs.stencil.so/tern/guides/routing.html)
- [Editor decorations](https://docs.stencil.so/tern/elements/input.html#editor)
- [Process API](https://docs.stencil.so/tern/reference/api-shared.html#ternprocessrun)
- [Kedi grammar package](https://pypi.org/project/tree-sitter-kedi/0.4.1/)
- [Python grammar and highlight query](https://github.com/tree-sitter/tree-sitter-python/tree/v0.25.0)
