"""The marker attributes are one contract, defined once.

The browser stamps `data-wg-*` attributes onto the live DOM and lxml reads them back after
parsing. Until `webgraph.markers` existed the names were written down three times -- as
Python constants in `fetch/render.py`, again as string literals inside the JavaScript those
same constants sat next to, and a third time in `dom/rich.py`. Nothing checked that the three
agreed. A rename that missed one copy would not have raised: the browser would stamp one
name, the parser would look for another, and every rect, line break or gate candidate would
quietly vanish. Silent total loss is the failure class this engine treats as intolerable.

These tests need no browser. They check the shape of the contract -- that the scripts load,
take the marker names as their argument rather than spelling them out, and that every
Python import site resolves to the *same* object. The render tests (`test_gates.py`,
`test_shadow_dom.py`, `test_render_integration.py`) are the proof the scripts still work.
"""

from __future__ import annotations

from importlib.resources import files

import pytest

from webgraph import markers
from webgraph.dom import rich
from webgraph.fetch import render

SCRIPTS = ("reveal", "gate_probe", "collect")
LITERALS = ("data-wg-id", "data-wg-brk", "data-wg-gate")


@pytest.mark.parametrize("name", SCRIPTS)
def test_script_loads_as_a_function_of_markers(name: str) -> None:
    source = render._script(name)
    assert source.strip(), f"{name}.js is empty"
    assert source.lstrip().startswith("(markers) =>"), (
        f"{name}.js must be an arrow function taking the marker names as its argument"
    )


@pytest.mark.parametrize("name", SCRIPTS)
def test_script_does_not_spell_out_the_attribute_names(name: str) -> None:
    source = render._script(name)
    for literal in LITERALS:
        assert literal not in source, (
            f"{name}.js hard-codes {literal!r}; the contract lives in webgraph.markers"
        )


def test_every_js_file_is_shipped_and_loadable() -> None:
    """A file present on disk but missing from the loader (or vice versa) is a packaging bug."""
    on_disk = sorted(p.name for p in (files("webgraph.fetch") / "js").iterdir())
    assert on_disk == sorted(f"{name}.js" for name in SCRIPTS)


def test_marker_arguments_carry_exactly_the_five_names() -> None:
    arguments = markers.marker_arguments()
    assert set(arguments) == {"marker", "brk", "gate", "hidden", "float"}
    assert arguments["hidden"] == markers.HIDDEN_ATTRIBUTE
    assert arguments["float"] == markers.FLOAT_ATTRIBUTE
    assert arguments["marker"] == markers.MARKER_ATTRIBUTE
    assert arguments["brk"] == markers.BREAK_ATTRIBUTE
    assert arguments["gate"] == markers.GATE_ATTRIBUTE


def test_python_import_sites_share_one_object() -> None:
    """`render` re-exports the names for existing importers; `rich` consumes one of them.

    Identity, not equality: an equal-but-separate string would mean someone typed the
    contract out a second time, which is exactly the drift this module exists to prevent."""
    assert render.MARKER_ATTRIBUTE is markers.MARKER_ATTRIBUTE
    assert render.BREAK_ATTRIBUTE is markers.BREAK_ATTRIBUTE
    assert render.GATE_ATTRIBUTE is markers.GATE_ATTRIBUTE
    assert rich.BREAK_ATTRIBUTE is markers.BREAK_ATTRIBUTE
