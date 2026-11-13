"""The code dependency graph: a derived, incrementally updated layer (design section 7.2).

* **Parsing.** tree-sitter extracts imports from Python and TypeScript (and
  TSX/JavaScript) file versions, then resolves them to files in the project.
  A bare package name stays external.
* **Incremental.** Parses are cached by the version's content id, so an
  update re-parses only files whose content changed. `last_update` reports
  how many were parsed and how many were reused.
* **Derived.** It is built from the file versions in the permanent core, kept
  in its own tables (`code_parse`, `code_edges`), and can be dropped and
  rebuilt at any time (`rebuild()`). It is not part of the core's integrity
  check.
* **Other languages.** These have no parser, so they get file-level history
  only. `supported(path)` says which are which, and verification falls back
  to whole-tree relevance for them (design 7.3).
"""
from __future__ import annotations

import json
import posixpath
import sqlite3
from datetime import datetime, timezone

import tree_sitter_python
import tree_sitter_typescript
from tree_sitter import Language, Parser, Query, QueryCursor

PY = Language(tree_sitter_python.language())
TS = Language(tree_sitter_typescript.language_typescript())
TSX = Language(tree_sitter_typescript.language_tsx())

LANGUAGES = {".py": ("python", PY), ".ts": ("typescript", TS), ".mts": ("typescript", TS), ".cts": ("typescript", TS),
             ".tsx": ("tsx", TSX), ".js": ("typescript", TS), ".mjs": ("typescript", TS),
             ".cjs": ("typescript", TS), ".jsx": ("tsx", TSX)}
TS_EXTENSIONS = (".ts", ".tsx", ".d.ts", ".js", ".jsx", ".mjs", ".cjs", ".mts", ".cts")
PY_SOURCE_ROOTS = ("", "src/", "lib/")

SCHEMA = """
CREATE TABLE IF NOT EXISTS code_parse (
    object_id TEXT PRIMARY KEY, language TEXT NOT NULL, imports TEXT NOT NULL, parsed_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS code_edges (
    from_path TEXT NOT NULL, to_path TEXT, type TEXT NOT NULL, spec TEXT NOT NULL);   -- to_path NULL: external
CREATE INDEX IF NOT EXISTS idx_code_edges_from ON code_edges(from_path);
CREATE INDEX IF NOT EXISTS idx_code_edges_to ON code_edges(to_path);
"""

# import ... from "x"; export ... from "x"; require("x"); import("x")
_IMPORT_QUERY = """
(import_statement source: (string (string_fragment) @spec))
(export_statement source: (string (string_fragment) @spec))
(call_expression function: (identifier) @fn arguments: (arguments (string (string_fragment) @spec)))
(call_expression function: (import) arguments: (arguments (string (string_fragment) @spec)))
"""
_TS_QUERY = Query(TS, _IMPORT_QUERY)
_TSX_QUERY = Query(TSX, _IMPORT_QUERY)


def supported(path: str) -> bool:
    return posixpath.splitext(path)[1] in LANGUAGES


def _text(node, source: bytes) -> str:
    return source[node.start_byte:node.end_byte].decode(errors="replace")


def parse_python(source: bytes) -> list[dict]:
    """Imports as {"module": "a.b", "level": dots, "names": [...]} records."""
    tree = Parser(PY).parse(source)
    found = []
    stack = [tree.root_node]
    while stack:
        node = stack.pop()
        if node.type == "import_statement":
            for child in node.named_children:
                target = child.child_by_field_name("name") if child.type == "aliased_import" else child
                if target is not None and target.type == "dotted_name":
                    found.append({"module": _text(target, source), "level": 0, "names": []})
        elif node.type == "import_from_statement":
            module_node = node.child_by_field_name("module_name")
            level, module = 0, ""
            if module_node is not None:
                if module_node.type == "relative_import":
                    for part in module_node.named_children:
                        if part.type == "import_prefix":
                            level = _text(part, source).count(".")
                        elif part.type == "dotted_name":
                            module = _text(part, source)
                else:
                    module = _text(module_node, source)
            names = []
            for child in node.children_by_field_name("name"):
                target = child.child_by_field_name("name") if child.type == "aliased_import" else child
                if target is not None:
                    names.append(_text(target, source))
            found.append({"module": module, "level": level, "names": names})
        else:
            stack.extend(reversed(node.children))
    return found


def parse_typescript(source: bytes, tsx: bool = False) -> list[dict]:
    language, query = (TSX, _TSX_QUERY) if tsx else (TS, _TS_QUERY)
    tree = Parser(language).parse(source)
    specs = []
    for _, captures in QueryCursor(query).matches(tree.root_node):
        fn = captures.get("fn")
        if fn and _text(fn[0], source) != "require":
            continue
        for node in captures.get("spec", []):
            specs.append({"spec": _text(node, source)})
    return specs


class CodeGraph:
    def __init__(self, conn_factory):
        self._connect = conn_factory
        self.last_update = {"parsed": 0, "reused": 0, "unsupported": 0}
        conn = self._connect()
        try:
            conn.executescript(SCHEMA)
        finally:
            conn.close()

    # ------------------------------------------------------------ current files
    @staticmethod
    def current_files(conn) -> dict[str, tuple[str, str]]:
        """Latest version of every path that exists now: {path: (object_id, event that produced it)}."""
        rows = conn.execute("""SELECT path, object_id, change, source_event FROM file_versions fv
                               WHERE log_position = (SELECT MAX(log_position) FROM file_versions WHERE path = fv.path)""")
        current = {}
        for path, oid, change, event in rows:
            if change != "deleted" and oid is not None:
                current[path] = (oid, event)
        # A rename leaves the old path behind.
        for (old,) in conn.execute("SELECT renamed_from FROM file_versions WHERE renamed_from IS NOT NULL"):
            later = conn.execute("SELECT MAX(log_position) FROM file_versions WHERE path = ?", (old,)).fetchone()[0]
            renamed_at = conn.execute("SELECT MAX(log_position) FROM file_versions WHERE renamed_from = ?",
                                      (old,)).fetchone()[0]
            if later is None or later < renamed_at:
                current.pop(old, None)
        return current

    # ------------------------------------------------------------ update
    def update(self, archive) -> dict:
        """Parse new file versions, re-resolve imports, and rewrite the derived edges."""
        conn = self._connect()
        try:
            current = self.current_files(conn)
            parsed = reused = unsupported = 0
            conn.execute("BEGIN IMMEDIATE")
            for path, (oid, _) in sorted(current.items()):
                if not supported(path):
                    unsupported += 1
                    continue
                if conn.execute("SELECT 1 FROM code_parse WHERE object_id = ?", (oid,)).fetchone():
                    reused += 1
                    continue
                language, _lang = LANGUAGES[posixpath.splitext(path)[1]]
                source = archive.get(oid)
                imports = parse_python(source) if language == "python" else parse_typescript(source, language == "tsx")
                conn.execute("INSERT INTO code_parse VALUES (?, ?, ?, ?)",
                             (oid, language, json.dumps(imports), datetime.now(timezone.utc).isoformat()))
                parsed += 1
            conn.execute("DELETE FROM code_edges")
            paths = set(current)
            for path, (oid, _) in sorted(current.items()):
                row = conn.execute("SELECT language, imports FROM code_parse WHERE object_id = ?", (oid,)).fetchone()
                if row is None:
                    continue
                for target, spec in self._resolve(path, row[0], json.loads(row[1]), paths):
                    conn.execute("INSERT INTO code_edges VALUES (?, ?, ?, ?)",
                                 (path, target, "imports" if target else "external", spec))
            conn.execute("COMMIT")
            self.last_update = {"parsed": parsed, "reused": reused, "unsupported": unsupported}
            return self.last_update
        except BaseException:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            raise
        finally:
            conn.close()

    def rebuild(self, archive) -> dict:
        conn = self._connect()
        try:
            conn.execute("DELETE FROM code_parse")
            conn.execute("DELETE FROM code_edges")
            conn.commit()
        finally:
            conn.close()
        return self.update(archive)

    # ------------------------------------------------------------ resolution
    @staticmethod
    def _resolve(path: str, language: str, imports: list[dict], paths: set[str]):
        if language == "python":
            here = posixpath.dirname(path)
            for imp in imports:
                if imp["level"]:
                    base = here
                    for _ in range(imp["level"] - 1):
                        base = posixpath.dirname(base)
                    stem = posixpath.join(base, *imp["module"].split(".")) if imp["module"] else base
                    candidates = [stem]
                    candidates += [posixpath.join(stem, n) for n in imp["names"]]
                    roots = [""]
                else:
                    stem = posixpath.join(*imp["module"].split("."))
                    candidates = [stem] + [posixpath.join(stem, n) for n in imp["names"]]
                    roots = list(PY_SOURCE_ROOTS)
                hit = False
                spec = imp["module"] or "." * imp["level"]
                for root in roots:
                    for c in candidates:
                        for file in (f"{root}{c}.py", f"{root}{c}/__init__.py"):
                            file = posixpath.normpath(file)
                            if file in paths and file != path:
                                hit = True
                                yield file, spec
                                # Importing a module runs every parent package's __init__.py.
                                parent = posixpath.dirname(file if not file.endswith("/__init__.py")
                                                           else posixpath.dirname(file))
                                while parent and parent + "/" != root and parent != root.rstrip("/"):
                                    init = f"{parent}/__init__.py"
                                    if init in paths and init != path:
                                        yield init, spec
                                    parent = posixpath.dirname(parent)
                if not hit:
                    yield None, ("." * imp["level"]) + imp["module"]
        else:
            here = posixpath.dirname(path)
            for imp in imports:
                spec = imp["spec"]
                if not spec.startswith("."):
                    yield None, spec
                    continue
                stem = posixpath.normpath(posixpath.join(here, spec))
                options = [stem] + [stem + ext for ext in TS_EXTENSIONS] + \
                          [posixpath.join(stem, "index" + ext) for ext in TS_EXTENSIONS]
                # TypeScript imports name the emitted .js file; map it back to the .ts source.
                if stem.endswith(".js"):
                    options += [stem[:-3] + ".ts", stem[:-3] + ".tsx"]
                target = next((o for o in options if o in paths), None)
                yield target, spec

    # ------------------------------------------------------------ queries
    def _edges(self, column: str, value: str) -> list[str]:
        conn = self._connect()
        try:
            other = "to_path" if column == "from_path" else "from_path"
            return sorted({r[0] for r in conn.execute(
                f"SELECT {other} FROM code_edges WHERE {column} = ? AND type = 'imports'", (value,))})
        finally:
            conn.close()

    def imports_of(self, path: str) -> list[str]:
        return self._edges("from_path", path)

    def importers_of(self, path: str) -> list[str]:
        return self._edges("to_path", path)

    def closure(self, paths, direction: str = "dependencies") -> set[str]:
        """Files reachable by imports (dependencies) or by being imported (dependents), including the start."""
        step = self.imports_of if direction == "dependencies" else self.importers_of
        seen, stack = set(paths), list(paths)
        while stack:
            for nxt in step(stack.pop()):
                if nxt not in seen:
                    seen.add(nxt)
                    stack.append(nxt)
        return seen

    def external_imports(self, path: str) -> list[str]:
        conn = self._connect()
        try:
            return sorted(r[0] for r in conn.execute(
                "SELECT spec FROM code_edges WHERE from_path = ? AND type = 'external'", (path,)))
        finally:
            conn.close()
