"""The docs keep telling the truth (Stage 1.8, #44).

Checks what can be checked mechanically, so drift is caught by CI:
* every capability the README says works today names code and tests that exist;
* the roadmap lists every stage, in order, with nothing missing (it once lost
  Phases 3-9 in an edit);
* every document states whether it is current, proposed, superseded or historical;
* relative links between documents resolve;
* corrected claims don't creep back into the README.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
README = (ROOT / "README.md").read_text()
DOCS = sorted([ROOT / "DESIGN.md", *(ROOT / "docs").glob("*.md"), *(ROOT / "docs" / "design").glob("*.md")])
STATUSES = ("Current", "Proposed", "Superseded", "Historical")


def works_today_rows():
    section = README.split("## Works today", 1)[1].split("\n## ", 1)[0]
    return [line for line in section.splitlines() if line.startswith("| ") and not line.startswith("| Capability")
            and not line.startswith("|---")]


def test_every_working_capability_names_existing_code_and_tests():
    rows = works_today_rows()
    assert len(rows) >= 15
    for row in rows:
        capability, where, tested = [c.strip() for c in row.strip("|").split("|")]
        tests = re.findall(r"`(tests/[^`]+\.py)`", tested)
        assert tests, f"no test named for: {capability}"
        for path in tests:
            assert (ROOT / path).is_file(), f"{capability}: {path} doesn't exist"
        for path in re.findall(r"`((?:kernel|memory|learning|interface|scripts|tests)/[^`]*)`", where):
            assert (ROOT / path.rstrip("/")).exists(), f"{capability}: {path} doesn't exist"


def test_every_memory_engine_capability_names_existing_code_and_tests():
    section = README.split("## Memory engine", 1)[1].split("\n## ", 1)[0]
    rows = [line for line in section.splitlines() if line.startswith("| ") and "`" in line.split("|")[2]]
    assert len(rows) >= 8
    package = ROOT / "packages" / "agent-memory"
    for row in rows:
        capability, where, tested = [c.strip() for c in row.strip("|").split("|")]
        tests = re.findall(r"`(packages/agent-memory/tests/[^`]+\.py)`", tested)
        assert tests, f"no test named for: {capability}"
        for path in tests:
            assert (ROOT / path).is_file(), f"{capability}: {path} doesn't exist"
        for name in re.findall(r"`([a-z_]+\.(?:py|toml))`", where):
            found = (package / "src" / "agent_memory" / name).is_file() or (package / name).is_file()
            assert found, f"{capability}: {name} doesn't exist in the engine package"


def test_the_readme_counts_the_roadmap_stages():
    total = re.search(r"(\d+) stages", (ROOT / "docs" / "ROADMAP.md").read_text()).group(1)
    assert f"{total}\nstages" in README or f"{total} stages" in README


def test_the_roadmap_lists_every_stage_in_order():
    text = (ROOT / "docs" / "ROADMAP.md").read_text()
    stages = re.findall(r"^\| (\d)\.(\d+) \| \[#(\d+)\]", text, re.M)
    total = int(re.search(r"(\d+) stages", text).group(1))
    assert len(stages) == total
    phases = [int(p) for p, _, _ in stages]
    assert phases == sorted(phases) and set(phases) == set(range(10))
    for phase in set(phases):
        numbers = [int(s) for p, s, _ in stages if int(p) == phase]
        assert numbers == list(range(1, len(numbers) + 1)), f"phase {phase} stages out of order: {numbers}"
    issues = [n for _, _, n in stages]
    assert len(issues) == len(set(issues)), "an issue appears twice"


@pytest.mark.parametrize("doc", DOCS, ids=lambda p: str(p.relative_to(ROOT)))
def test_every_document_states_its_status(doc):
    head = "\n".join(doc.read_text().splitlines()[:10])
    match = re.search(r"\*\*Status:\*\*\s*(\w+)", head)
    assert match, f"{doc.name} has no status line"
    assert match.group(1) in STATUSES, f"{doc.name}: unexpected status {match.group(1)!r}"


@pytest.mark.parametrize("doc", [ROOT / "README.md", *DOCS], ids=lambda p: str(p.relative_to(ROOT)))
def test_relative_links_resolve(doc):
    for target in re.findall(r"\]\((?!https?:|#|mailto:)([^)\s#]+)", doc.read_text()):
        assert (doc.parent / target).exists(), f"{doc.name} links to missing {target}"


@pytest.mark.parametrize("claim", ["LanceDB", "bge-small", "fastembed", "backward chaining",
                                   "first of its kind", "16 Layer 1 rules", "O(n)"])
def test_corrected_claims_stay_out_of_the_readme(claim):
    assert claim.lower() not in README.lower()
