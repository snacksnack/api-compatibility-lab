"""The generated module: it has to be valid, lintable, and deterministic."""

from __future__ import annotations

import ast
import subprocess
import sys

import pytest

from compatlab import VERSION_A, VERSION_B
from compatlab.codegen import WIDTH, render_module, render_test
from compatlab.pinning import compile_pin
from tests.test_pinning import make_pin, record


def compiled(**over):
    """One compiled pin, with its own step so the names stay distinct."""
    fields = {k: v for k, v in over.items() if k != "body"}
    step = fields.pop("step", None)
    if step:
        fields["corpus"] = f"w.{step}"
        fields["pin"] = f"w.{step} {fields.get('locus', '$.body.count')}"
    pin = make_pin(**fields)
    body = over.get("body", {"count": 1})
    return compile_pin(pin, None if body is None else record(body, step=step))


EVERY_KIND = [
    compiled(),
    compiled(step="status_step", locus="$.status", axis="status",
             rule="status-class-changed",
             assertion="`w.status_step` returns status 200 and not 404"),
    compiled(step="emptied", rule="list-emptied", locus="$.body.data",
             body={"data": [{"amount": 3000}]}),
    compiled(step="truncated", rule="list-truncated", locus="$.body.data",
             body={"data": [1, 2, 3]}),
    compiled(step="gone", rule="step-missing", locus="$.status", body=None),
    compiled(step="nested", locus="$.body.nested",
             body={"nested": {"a": {"b": [1]}}}),
    compiled(step="flag", locus="$.body.paid", body={"paid": True}),
    compiled(step="apm", locus="$.body.apm", body={"apm": None}),
]


def test_the_module_is_valid_python():
    ast.parse(render_module(EVERY_KIND, VERSION_A, VERSION_B))


def test_every_assertion_kind_renders():
    """A kind with no renderer raises rather than emitting nothing."""
    kinds = {test.kind for test in EVERY_KIND}
    assert len(kinds) == 6
    for test in EVERY_KIND:
        assert "assert " in render_test(test, VERSION_A, VERSION_B)


def test_a_boolean_is_pinned_with_is_not_equality():
    """`== True` is a lint error, and `assert value` passes on any truthy."""
    source = render_test(compiled(locus="$.body.paid", body={"paid": True}),
                         VERSION_A, VERSION_B)
    assert "is True" in source


def test_null_is_pinned_as_null_not_as_falsy():
    source = render_test(compiled(locus="$.body.apm", body={"apm": None}),
                         VERSION_A, VERSION_B)
    assert "is None" in source


def test_generation_is_deterministic():
    one = render_module(EVERY_KIND, VERSION_A, VERSION_B)
    two = render_module(EVERY_KIND, VERSION_A, VERSION_B)
    assert one == two


def test_nothing_exceeds_the_project_line_length():
    """A generated file that fails the repo's linter is one somebody edits."""
    source = render_module(EVERY_KIND, VERSION_A, VERSION_B)
    assert [line for line in source.splitlines() if len(line) > WIDTH] == []


def test_a_long_value_in_a_docstring_is_wrapped_not_truncated():
    long = "Z" * 300
    source = render_test(compiled(observed_on_b=long), VERSION_A, VERSION_B)
    assert [line for line in source.splitlines() if len(line) > WIDTH] == []
    assert source.count("Z") == 300  # folded across lines, not clipped


def test_a_pin_cannot_close_the_docstring_it_is_quoted_in():
    source = render_test(compiled(observed_on_b='he said """stop"""'),
                         VERSION_A, VERSION_B)
    ast.parse(source)


def test_the_module_imports_only_what_it_uses():
    """An unused import is a lint error in a file nobody wrote."""
    source = render_module([compiled()], VERSION_A, VERSION_B)
    imports = [line for line in source.splitlines() if line.startswith("from ")]
    assert imports == ["from compatlab.loci import value_at"]


def test_the_generated_module_passes_the_projects_linter(tmp_path):
    path = tmp_path / "test_generated.py"
    path.write_text(render_module(EVERY_KIND, VERSION_A, VERSION_B))
    proc = subprocess.run(
        [sys.executable, "-m", "ruff", "check", "--select", "E,F,I,UP,B,W",
         "--line-length", str(WIDTH), str(path)],
        capture_output=True, text=True, check=False)
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_an_unknown_kind_raises_rather_than_rendering_nothing():
    broken = compiled()
    with pytest.raises(ValueError, match="no renderer"):
        render_test(type(broken)(pin=broken.pin, name=broken.name,
                                 kind="invented", expected=None, reason=""),
                    VERSION_A, VERSION_B)
