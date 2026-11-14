"""Stage 2.7 (#86): symbols, tsconfig aliases, documents, metadata, artifact search and navigation."""
from __future__ import annotations

import pytest

from agent_memory import EventInput, Store

ENV = {"interpreters": {"python": "3.12"}, "os": "linux"}


def put(store, path: str, content: bytes | str, session: str = "s1"):
    data = content.encode() if isinstance(content, str) else content
    return store.append(EventInput(kind="file_change", session_id=session, writer_id="w", payload=data,
                                   summary_fields={"path": path, "size": len(data)}, path=path))


PY_SOURCE = '''import os


class Store:
    """A store."""

    def append(self, event):
        def helper():
            return 1
        return helper()

    @property
    def size(self):
        return 0


def open_store(path):
    return Store()


async def fetch():
    pass
'''

TS_SOURCE = '''import { verify } from "@/auth/jwt";

export interface Session { id: string }
export type Token = string;
export enum Role { Admin, User }

export class AuthService {
  login(user: string): Token { return verify(user); }
  private refresh() {}
}

export function issueToken(): Token { return ""; }
export const revoke = (t: Token) => {};
'''


# ---------------------------------------------------------------- symbols
def test_python_symbols_are_found_by_name_and_qualified_name(store):
    put(store, "pkg/store.py", PY_SOURCE)
    parts = {p["qualified"]: (p["kind"], p["line"]) for p in store.artifacts.parts("pkg/store.py")}
    assert parts == {"Store": ("class", 4), "Store.append": ("method", 7), "Store.append.helper": ("function", 8),
                     "Store.size": ("method", 13), "open_store": ("function", 17), "fetch": ("function", 21)}
    (hit,) = store.artifacts.find_part("open_store")
    assert (hit["path"], hit["line"], hit["end_line"]) == ("pkg/store.py", 17, 18)
    assert [h["qualified"] for h in store.artifacts.find_part("append")] == ["Store.append"]
    assert [h["qualified"] for h in store.artifacts.find_part("Store.append")] == ["Store.append"]
    assert store.artifacts.find_part("Store", kind="function") == []


def test_typescript_symbols_are_found(store):
    put(store, "src/auth/service.ts", TS_SOURCE)
    parts = {p["qualified"]: p["kind"] for p in store.artifacts.parts("src/auth/service.ts")}
    assert parts == {"Session": "interface", "Token": "type", "Role": "enum", "AuthService": "class",
                     "AuthService.login": "method", "AuthService.refresh": "method", "issueToken": "function",
                     "revoke": "function"}
    assert store.artifacts.find_part("login")[0]["path"] == "src/auth/service.ts"


def test_a_symbol_moves_with_its_file_and_old_versions_drop_out(store):
    put(store, "a.py", "def first():\n    pass\n")
    assert store.artifacts.find_part("first")
    put(store, "a.py", "def second():\n    pass\n")
    assert store.artifacts.find_part("first") == [] and store.artifacts.find_part("second")


# ---------------------------------------------------------------- tsconfig aliases (#78)
TSCONFIG_BASE = '''{
  // shared options
  "compilerOptions": {
    "baseUrl": ".",
    "paths": { "@/*": ["src/*"], "@lib": ["src/lib/index.ts"], },
  },
}
'''


def alias_project(store):
    put(store, "tsconfig.base.json", TSCONFIG_BASE)
    put(store, "tsconfig.json", '{ "extends": "./tsconfig.base.json", /* app */ "include": ["src"] }')
    put(store, "src/auth/jwt.ts", "export function verify(u: string) { return u; }\n")
    put(store, "src/lib/index.ts", "export const lib = 1;\n")
    put(store, "src/api/routes.ts", 'import { verify } from "@/auth/jwt";\nimport { lib } from "@lib";\n'
                                    'import React from "react";\nexport const r = verify("x") + lib;\n')
    put(store, "tests/routes.test.ts", 'import { r } from "../src/api/routes";\nexport const t = r;\n')


def test_tsconfig_path_aliases_resolve_including_extends(store):
    alias_project(store)
    deps = store.artifacts.depends("src/api/routes.ts")
    assert deps["artifacts"] == ["src/auth/jwt.ts", "src/lib/index.ts"]
    assert deps["external"] == ["react"] and deps["unresolved"] == []
    assert store.artifacts.depends("src/auth/jwt.ts", "dependents")["artifacts"] == ["src/api/routes.ts"]
    assert store.artifacts.depends("tests/routes.test.ts", closure=True)["artifacts"] == [
        "src/api/routes.ts", "src/auth/jwt.ts", "src/lib/index.ts"]


def test_changing_a_file_reached_only_through_an_alias_makes_the_test_stale(store):
    alias_project(store)
    check = store.record_verification("s1", "w", "vitest", "passed", 0, targets=["tests/routes.test.ts"],
                                      environment=ENV)
    assert check.summary_fields["relevance_method"] == "import_closure"
    assert "src/auth/jwt.ts" in check.summary_fields["relevant_files"]
    assert store.verification_status(check.event_id, ENV)["status"] == "verified"
    put(store, "src/auth/jwt.ts", "export function verify(u: string) { return u + '!'; }\n")
    status = store.verification_status(check.event_id, ENV)
    assert status["status"] == "stale" and status["reasons"][0].startswith("src/auth/jwt.ts changed")


def test_an_unresolved_local_import_falls_back_to_the_whole_tree(store):
    alias_project(store)
    put(store, "src/api/routes.ts", 'import { gone } from "@/auth/missing";\nexport const r = gone;\n')
    put(store, "unrelated.md", "# notes\n")
    check = store.record_verification("s1", "w", "vitest", "passed", 0, targets=["tests/routes.test.ts"],
                                      environment=ENV)
    s = check.summary_fields
    assert s["relevance_method"] == "whole_tree"
    assert s["unresolved_imports"] == {"src/api/routes.ts": ["@/auth/missing"]}
    put(store, "unrelated.md", "# notes, edited\n")   # whole-tree relevance: any change counts
    assert store.verification_status(check.event_id, ENV)["status"] == "stale"


def test_an_unresolved_python_relative_import_is_local_not_external(store):
    put(store, "pkg/a.py", "from .missing import thing\nimport requests\n")
    deps = store.artifacts.depends("pkg/a.py")
    assert deps["unresolved"] == [".missing"] and deps["external"] == ["requests"]


# ---------------------------------------------------------------- documents
GUIDE = """# Guide

Intro with a [link to b](./b.md#part) and [the readme](../README.md) and [a site](https://example.com).

## Install

```bash
# not a heading
pip install x
```

### On Windows

Use WSL.

## Usage

Run it. ![logo](img/logo.png)

Appendix
--------

The end.
"""


def test_markdown_sections_are_navigable_parts(store):
    put(store, "docs/guide.md", GUIDE)
    sections = {p["qualified"]: (p["line"], p["end_line"], p["parent"]) for p in store.artifacts.parts("docs/guide.md")}
    assert sections == {
        "Guide": (1, 23, None),
        "Guide > Install": (5, 15, "Guide"),
        "Guide > Install > On Windows": (12, 15, "Guide > Install"),
        "Guide > Usage": (16, 19, "Guide"),
        "Guide > Appendix": (20, 23, "Guide"),   # setext heading
    }
    assert [h["qualified"] for h in store.artifacts.find_part("On Windows", kind="section")] == [
        "Guide > Install > On Windows"]
    node = store.artifacts.open_path("docs/guide.md")
    assert node["parts"] == 5 and node["metadata"]["media_type"] == "text/markdown"


def test_links_between_documents_are_dependency_edges(store):
    put(store, "README.md", "# Project\n\nSee [the guide](docs/guide.md).\n")
    put(store, "docs/b.md", "# B\n")
    put(store, "docs/guide.md", GUIDE)
    assert store.artifacts.depends("docs/guide.md")["artifacts"] == ["README.md", "docs/b.md"]
    assert store.artifacts.depends("docs/b.md", "dependents")["artifacts"] == ["docs/guide.md"]
    assert store.artifacts.depends("README.md", closure=True)["artifacts"] == ["docs/b.md", "docs/guide.md"]


def test_restructuredtext_sections(store):
    put(store, "docs/api.rst", "API\n===\n\nIntro.\n\nClients\n-------\n\nText.\n\nServers\n-------\n\nMore.\n")
    assert [(p["qualified"], p["line"]) for p in store.artifacts.parts("docs/api.rst")] == [
        ("API", 1), ("API > Clients", 6), ("API > Servers", 11)]


def test_without_the_documents_profile_documents_have_no_sections(tmp_path):
    store = Store(tmp_path / "s", project_id="p", min_free_bytes=0, profiles=("generic", "software"))
    put(store, "docs/guide.md", GUIDE)
    assert store.artifacts.parts("docs/guide.md") == []
    assert store.artifacts.search("WSL")   # search is generic


# ---------------------------------------------------------------- any artifact
PNG = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR" + bytes(range(256)) * 4


def test_a_binary_artifact_has_versions_and_metadata_without_a_parser(store):
    put(store, "assets/logo.png", PNG)
    put(store, "assets/logo.png", PNG + b"\x00more")
    meta = store.artifacts.metadata("assets/logo.png")
    assert meta == {"media_type": "image/png", "size": len(PNG) + 5, "is_text": False, "lines": None}
    assert len(store.artifacts.versions("assets/logo.png")) == 2
    assert store.artifacts.parts("assets/logo.png") == []
    assert store.artifacts.at("assets/logo.png", 0)["content"] == PNG
    node = store.artifacts.open_path("assets/logo.png")
    assert node["present"] and node["metadata"]["is_text"] is False
    assert [i["label"] for i in store.artifacts.open_path("assets")["items"]] == ["logo.png"]


def test_any_version_can_be_read_back_with_a_size_bound(store):
    put(store, "notes.txt", "first\n")
    put(store, "notes.txt", "second version, longer\n")
    assert store.artifacts.at("notes.txt", 0)["content"] == b"first\n"
    latest = store.artifacts.at("notes.txt", max_bytes=6)
    assert latest == {**latest, "content": b"second", "truncated": True}
    first_id = store.artifacts.versions("notes.txt")[0]["version_id"]
    assert store.artifacts.at("notes.txt", first_id)["content"] == b"first\n"
    with pytest.raises(KeyError):
        store.artifacts.at("missing.txt")


# ---------------------------------------------------------------- search
def test_full_text_search_covers_current_text_artifacts_only(store):
    put(store, "a.md", "The refresh token rotates on every use.\n")
    put(store, "b.py", "def rotate():\n    '''rotate the refresh token'''\n")
    put(store, "c.txt", "old text about refresh\n")
    put(store, "c.txt", "new text\n")
    put(store, "logo.png", PNG)
    found = {h["path"] for h in store.artifacts.search("refresh token")}
    assert found == {"a.md", "b.py"}
    hit = store.artifacts.search("rotates")[0]
    assert hit["path"] == "a.md" and "[rotates]" in hit["snippet"]
    assert store.artifacts.search('"; DROP TABLE x; --') == []   # input is quoted, never FTS syntax


def test_search_never_finds_a_redacted_secret(store):
    token = "gh" + "p_" + "Ab3dEf6hIj9kLm2nOp5qRs8tUv1wXy4zAb7d"
    put(store, "deploy.sh", f"export TOKEN={token}\necho deploying\n")
    assert store.artifacts.search(token) == []
    assert store.artifacts.search("deploying")[0]["path"] == "deploy.sh"


def test_the_index_is_incremental_and_rebuildable(store):
    put(store, "a.py", "def f():\n    pass\n")
    put(store, "b.md", "# B\n")
    first = store.update_artifacts()
    again = store.update_artifacts()
    assert again["parsed"] == 0 and again["described"] == 0 and again["reused"] == 2
    before = (store.artifacts.find_part("f"), store.artifacts.search("B"))
    assert store.rebuild_derived()["parsed"] == 2
    assert (store.artifacts.find_part("f"), store.artifacts.search("B")) == before
    assert first["described"] == 2
    assert store.verify()["ok"]


def test_python_imports_resolve_in_a_monorepo_package_root(store):
    put(store, "packages/engine/src/engine/__init__.py", "")
    put(store, "packages/engine/src/engine/keys.py", "KEY = 1\n")
    put(store, "packages/engine/src/engine/store.py", "from engine import keys\nfrom engine.keys import KEY\n")
    put(store, "app/main.py", "import engine.store\n")
    deps = store.artifacts.depends("packages/engine/src/engine/store.py")
    assert deps["artifacts"] == ["packages/engine/src/engine/__init__.py", "packages/engine/src/engine/keys.py"]
    assert "packages/engine/src/engine/store.py" in store.artifacts.depends("app/main.py")["artifacts"]
