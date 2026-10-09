import json
import subprocess
import sys
from pathlib import Path

import pytest

from kedi_tern.highlight import (
    MAX_SOURCE_BYTES,
    Capture,
    grammar,
    highlight,
    python_grammar,
    resolve_overlaps,
    token_for_capture,
    utf16_offsets,
)

ROOT = Path(__file__).resolve().parents[1]


def colored_text(source, result):
    encoded = source.encode("utf-16-le")
    return [
        (encoded[span["from"] * 2 : span["to"] * 2].decode("utf-16-le"), span["s"])
        for span in result["decorations"]
    ]


def test_every_public_grammar_capture_has_a_mapping():
    _, query = grammar()
    for i in range(query.capture_count):
        name = query.capture_name(i)
        if not name.startswith("_"):
            assert token_for_capture(name) is not None, name
    assert token_for_capture("_query_artifacts") is None


def test_dotted_mapping_prefers_exact_then_parents():
    assert token_for_capture("comment.line") == "syntaxComment"
    assert token_for_capture("constant.builtin") == "syntaxKeyword"
    assert token_for_capture("variable.parameter") == "syntaxVariable"
    assert token_for_capture("unknown.kind") is None


def test_unicode_offsets_include_astral_characters_and_crlf():
    source = "aş🐈\r\nx"
    result, length = utf16_offsets(source, {0, 1, 3, 7, 9, 10})
    assert result == {0: 0, 1: 1, 3: 2, 7: 4, 9: 6, 10: 7}
    assert length == 7
    with pytest.raises(ValueError, match="boundary"):
        utf16_offsets(source, {2})


def test_overlap_policy_and_adjacent_merge():
    captures = [
        Capture(0, 20, "syntaxString"),
        Capture(5, 10, "syntaxFunction"),
        Capture(5, 10, "syntaxType", pattern=2),
        Capture(10, 12, "syntaxType"),
        Capture(15, 18, "syntaxKeyword", priority=10),
        Capture(16, 17, "syntaxVariable"),
    ]
    assert resolve_overlaps(captures) == [
        (0, 5, "syntaxString"),
        (5, 12, "syntaxType"),
        (12, 15, "syntaxString"),
        (15, 18, "syntaxKeyword"),
        (18, 20, "syntaxString"),
    ]
    assert resolve_overlaps(list(reversed(captures))) == resolve_overlaps(captures)


def test_overlap_gaps_and_empty_captures():
    assert resolve_overlaps(
        [
            Capture(0, 0, "syntaxKeyword"),
            Capture(1, 2, "syntaxString"),
            Capture(3, 4, "syntaxString"),
        ]
    ) == [(1, 2, "syntaxString"), (3, 4, "syntaxString")]


def test_real_grammar_highlights_unicode_comments_and_functions():
    source = "# Türkçe 🐈\n@greet(name: str) -> str:\n    >> Merhaba <name>\n"
    result = highlight(source)
    spans = colored_text(source, result)
    assert result["has_errors"] is False
    assert ("# Türkçe 🐈", "syntaxComment") in spans
    assert ("greet", "syntaxFunction") in spans
    assert ("name", "syntaxVariable") in spans
    assert ("str", "syntaxType") in spans
    assert result["utf16_length"] == len(source.encode("utf-16-le")) // 2
    for left, right in zip(result["decorations"], result["decorations"][1:], strict=False):
        assert left["to"] <= right["from"]


def test_predicates_are_applied_without_coloring_private_captures():
    source = "@main():\n    > artifacts:\n        query_artifacts: auto\n        other: auto\n"
    result = highlight(source)
    assert result["has_errors"] is False
    spans = colored_text(source, result)
    assert ("auto", "syntaxKeyword") in spans
    assert ("auto", "syntaxString") in spans
    assert ("query_artifacts", "syntaxVariable") in spans


def test_empty_source_and_incomplete_source():
    assert highlight("") == {
        "schema": 1,
        "utf16_length": 0,
        "has_errors": False,
        "decorations": [],
    }
    result = highlight("@broken(\n")
    assert result["has_errors"] is True
    assert isinstance(result["decorations"], list)


def test_large_input_is_rejected():
    with pytest.raises(ValueError, match="1 MiB"):
        highlight("x" * (MAX_SOURCE_BYTES + 1))


def run_cli(source):
    return subprocess.run(
        [sys.executable, str(ROOT / "python/highlight.py")],
        input=source,
        capture_output=True,
        cwd=ROOT.parent,
        check=False,
    )


def test_cli_works_outside_plugin_directory():
    result = run_cli("# 🐈\n".encode())
    assert result.returncode == 0, result.stderr
    assert not result.stderr
    assert json.loads(result.stdout)["decorations"] == [
        {"from": 0, "to": 4, "s": "syntaxComment"},
    ]


@pytest.mark.parametrize(
    "source", [b"\xff", b"x" * (MAX_SOURCE_BYTES + 1)], ids=["invalid-utf8", "too-large"]
)
def test_cli_errors_do_not_pollute_json_stdout(source):
    result = run_cli(source)
    assert result.returncode == 1
    assert result.stdout == b""
    assert b"kedi-tern:" in result.stderr


def token_at(source, result, needle):
    position = len(source[: source.index(needle)].encode("utf-16-le")) // 2
    return next(
        (span["s"] for span in result["decorations"] if span["from"] <= position < span["to"]),
        None,
    )


def test_every_python_capture_has_a_mapping():
    _, query = python_grammar()
    for i in range(query.capture_count):
        name = query.capture_name(i)
        assert token_for_capture(name) is not None, name


@pytest.mark.parametrize("indent", ["", "    "])
def test_fenced_python_tokens_and_neutral_gaps(indent):
    python = "import math\n# Python comment\nanswer = math.sqrt(42)\n"
    block = "```\n" + python + "```\n"
    source = ("@main():\n" if indent else "") + "".join(
        indent + line for line in block.splitlines(keepends=True)
    )
    result = highlight(source)
    assert result["has_errors"] is False
    for needle, token in {
        "```": "syntaxPunctuation",
        "import": "syntaxKeyword",
        "# Python comment": "syntaxComment",
        "answer": "syntaxVariable",
        "sqrt": "syntaxFunction",
        "42": "syntaxNumber",
        "(42": "syntaxVariable",  # Neutral punctuation, not the outer string color.
    }.items():
        assert token_at(source, result, needle) == token


@pytest.mark.parametrize("statement", ["[value] =", "[value] :=", "="])
def test_python_in_fenced_assignments_and_returns(statement):
    source = f"@main():\n    {statement} ```\n    sum([1, 2])\n    ```\n"
    result = highlight(source)
    assert result["has_errors"] is False
    assert token_at(source, result, "sum") == "syntaxFunction"
    assert token_at(source, result, "1") == "syntaxNumber"


def test_inline_python_defaults_types_and_expressions():
    source = (
        "@main(value: `list[int]` = `[1, 2]`):\n    [result] = `len(value) + 3`\n    = `result`\n"
    )
    result = highlight(source)
    assert result["has_errors"] is False
    assert token_at(source, result, "main") == "syntaxFunction"
    assert token_at(source, result, "`list") == "syntaxPunctuation"
    assert token_at(source, result, "list") == "syntaxVariable"
    assert token_at(source, result, "1") == "syntaxNumber"
    assert token_at(source, result, "len") == "syntaxFunction"
    assert token_at(source, result, "+") == "syntaxOperator"
    assert token_at(source, result, "3") == "syntaxNumber"


@pytest.mark.parametrize("newline", ["\n", "\r\n"], ids=["lf", "crlf"])
def test_python_fstrings_and_unicode_keep_document_offsets(newline):
    source = (
        '# Önce 🐈\n```\nmessage = f"Merhaba {name.upper()} 🐈"\n```\n'
        '@after():\n    = `len("ş🐈") + 7`\n'
    ).replace("\n", newline)
    result = highlight(source)
    assert result["has_errors"] is False
    for needle, token in {
        "# Önce": "syntaxComment",
        "Merhaba": "syntaxString",
        "{name": "syntaxPunctuation",
        "name": "syntaxVariable",
        "upper": "syntaxFunction",
        "after": "syntaxFunction",
        "len": "syntaxFunction",
        "7": "syntaxNumber",
    }.items():
        assert token_at(source, result, needle) == token
    assert result["utf16_length"] == len(source.encode("utf-16-le")) // 2
    for span in result["decorations"]:
        source.encode("utf-16-le")[span["from"] * 2 : span["to"] * 2].decode("utf-16-le")
    for left, right in zip(result["decorations"], result["decorations"][1:], strict=False):
        assert left["to"] <= right["from"]


def test_invalid_python_does_not_swallow_following_kedi():
    source = "```\ndef broken(:\n```\n@after():\n    >> Still Kedi\n"
    result = highlight(source)
    assert result["has_errors"] is True
    assert token_at(source, result, "def") == "syntaxKeyword"
    assert token_at(source, result, "after") == "syntaxFunction"
    assert token_at(source, result, "Still Kedi") == "syntaxString"


def test_legacy_system_is_not_rewritten_or_accepted():
    source = (
        "```\nimport logfire\n```\n> profile: researcher:\n    > system:\n        Be concise.\n"
    )
    result = highlight(source)
    assert result["has_errors"] is True
    assert token_at(source, result, "import") == "syntaxKeyword"
    assert result["utf16_length"] == len(source.encode("utf-16-le")) // 2
