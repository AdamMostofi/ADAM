"""The artifact index: a derived, incrementally updated layer over the artifact tree (revision 3, section 4.2).

Everything here is computed from the archived content of the current
artifact versions. It is cached by content id, kept in its own tables, and can
be dropped and rebuilt at any time (`rebuild()`). The permanent core stays a
pure function of the log.

**For every artifact (generic profile):**
- metadata: media type, size, whether it is text, line count;
- full-text search over text artifacts (`search()`, SQLite FTS5). Only
  permitted content is indexed: the archive already holds redacted text, and
  excluded files are never archived.

**Software profile:** tree-sitter parsers for Python and TypeScript (with
TSX/JavaScript) extract:
- **imports**, resolved to files in the project. TypeScript `tsconfig.json`
  `baseUrl` and `paths` aliases are honoured, `extends` included.
- **symbols** (classes, functions, methods, interfaces, types, enums, arrow
  functions bound to names), stored as artifact parts with line ranges. Nested
  symbols are qualified, for example `Store.append`.

**Documents profile:** Markdown (and reStructuredText) headings become
`section` parts with line ranges and nesting. Relative links to other
artifacts become `links` edges.

**Unresolved local imports** are recorded as `unresolved` edges:
- a relative import or a tsconfig-alias import that names no file, or
- a Python relative import that matches nothing.

Verification relevance falls back to the whole tree when its closure
contains one, so a missed edge can never produce a false "verified" (#78).
"""
from __future__ import annotations

import json
import mimetypes
import posixpath
import re
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
DOCUMENTS = {".md": "markdown", ".markdown": "markdown", ".mdx": "markdown", ".rst": "rst"}
TS_EXTENSIONS = (".ts", ".tsx", ".d.ts", ".js", ".jsx", ".mjs", ".cjs", ".mts", ".cts")
PY_SOURCE_ROOTS = ("", "src/", "lib/")


def python_roots(paths: set[str]) -> tuple[str, ...]:
    """Where top-level Python packages live: the usual roots, plus the parent of every outermost package.

    In a monorepo (for example `packages/engine/src/engine/__init__.py`) the
    source root is `packages/engine/src/`, so `import engine.x` resolves there.
    """
    roots = set(PY_SOURCE_ROOTS)
    for path in paths:
        if posixpath.basename(path) == "__init__.py":
            package = posixpath.dirname(path)
            parent = posixpath.dirname(package)
            if parent and posixpath.join(parent, "__init__.py") not in paths:
                roots.add(parent + "/")
    return tuple(sorted(roots, key=lambda r: (len(r), r)))
FTS_MAX_BYTES = 2_000_000
PARSER_VERSION = 2   # bump to re-parse cached objects when a parser changes

SCHEMA = """
DROP TABLE IF EXISTS code_parse;
CREATE TABLE IF NOT EXISTS artifact_parse (
    object_id TEXT NOT NULL, parser TEXT NOT NULL, version INTEGER NOT NULL, deps TEXT NOT NULL,
    parts TEXT NOT NULL, parsed_at TEXT NOT NULL, PRIMARY KEY (object_id, parser));
CREATE TABLE IF NOT EXISTS artifact_meta (
    object_id TEXT PRIMARY KEY, media_type TEXT, size INTEGER NOT NULL, is_text INTEGER NOT NULL, lines INTEGER);
CREATE TABLE IF NOT EXISTS artifact_parts (
    path TEXT NOT NULL, name TEXT NOT NULL, qualified TEXT NOT NULL, kind TEXT NOT NULL, line INTEGER NOT NULL,
    end_line INTEGER NOT NULL, parent TEXT, object_id TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS idx_parts_name ON artifact_parts(name);
CREATE INDEX IF NOT EXISTS idx_parts_path ON artifact_parts(path);
CREATE TABLE IF NOT EXISTS code_edges (
    from_path TEXT NOT NULL, to_path TEXT, type TEXT NOT NULL, spec TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS idx_code_edges_from ON code_edges(from_path);
CREATE INDEX IF NOT EXISTS idx_code_edges_to ON code_edges(to_path);
CREATE VIRTUAL TABLE IF NOT EXISTS artifact_fts USING fts5(path UNINDEXED, object_id UNINDEXED, body);
"""
# code_edges.type: imports | links (to an artifact) | external (a package) | unresolved (local, but no file found)

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
    """True if the software profile has a parser for this path (code)."""
    return posixpath.splitext(path)[1] in LANGUAGES


def is_document(path: str) -> bool:
    return posixpath.splitext(path)[1].lower() in DOCUMENTS


def _text(node, source: bytes) -> str:
    return source[node.start_byte:node.end_byte].decode(errors="replace")


# ------------------------------------------------------------ code: imports
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


# ------------------------------------------------------------ code: symbols
PY_SYMBOLS = {"class_definition": "class", "function_definition": "function"}
TS_SYMBOLS = {"class_declaration": "class", "abstract_class_declaration": "class",
              "function_declaration": "function", "generator_function_declaration": "function",
              "method_definition": "method", "interface_declaration": "interface",
              "type_alias_declaration": "type", "enum_declaration": "enum"}
TS_SCOPES = {"class_body", "statement_block", "program", "export_statement", "interface_body"}


def _symbols(root, source: bytes, table: dict, typescript: bool) -> list[dict]:
    parts: list[dict] = []

    def visit(node, scope: list[str]) -> None:
        kind = table.get(node.type)
        name_node = node.child_by_field_name("name") if kind else None
        # const f = () => ... / const f = function () {...}
        if typescript and node.type == "variable_declarator":
            value = node.child_by_field_name("value")
            if value is not None and value.type in ("arrow_function", "function_expression", "function"):
                kind, name_node = "function", node.child_by_field_name("name")
        if kind and name_node is not None:
            name = _text(name_node, source)
            if kind == "function" and scope and not typescript:
                kind = "method" if parts and any(p["qualified"] == ".".join(scope) and p["kind"] == "class"
                                                 for p in parts) else "function"
            qualified = ".".join([*scope, name])
            parts.append({"name": name, "qualified": qualified, "kind": kind,
                          "line": node.start_point[0] + 1, "end_line": node.end_point[0] + 1,
                          "parent": ".".join(scope) or None})
            if kind in ("class", "function", "method", "interface"):
                for child in node.children:
                    visit(child, [*scope, name])
                return
        for child in node.children:
            visit(child, scope)

    visit(root, [])
    return parts


def python_symbols(source: bytes) -> list[dict]:
    return _symbols(Parser(PY).parse(source).root_node, source, PY_SYMBOLS, typescript=False)


def typescript_symbols(source: bytes, tsx: bool = False) -> list[dict]:
    return _symbols(Parser(TSX if tsx else TS).parse(source).root_node, source, TS_SYMBOLS, typescript=True)


# ------------------------------------------------------------ documents
_FENCE = re.compile(r"^\s*(```|~~~)")
_ATX = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")
_MD_LINK = re.compile(r"(?<!!)\[[^\]]*\]\(\s*<?([^)\s>]+)>?(?:\s+\"[^\"]*\")?\s*\)")
_RST_UNDERLINE = re.compile(r"^([=\-~^\"'`#*+])\1{2,}\s*$")


def document_sections(source: bytes, kind: str) -> tuple[list[dict], list[str]]:
    """(sections, link targets) for a Markdown or reStructuredText document."""
    lines = source.decode("utf-8", errors="replace").splitlines()
    heads: list[tuple[int, int, str]] = []   # (line number, level, title)
    links: list[str] = []
    in_fence = False
    rst_levels: list[str] = []
    for i, line in enumerate(lines):
        if _FENCE.match(line):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        if kind == "markdown":
            m = _ATX.match(line)
            if m:
                heads.append((i + 1, len(m.group(1)), m.group(2).strip()))
            elif i > 0 and lines[i - 1].strip() and re.match(r"^(=+|-+)\s*$", line) and \
                    not (heads and heads[-1][0] == i) and not lines[i - 1].lstrip().startswith(("-", "*", ">")):
                heads.append((i, 1 if line.strip()[0] == "=" else 2, lines[i - 1].strip()))   # setext
            links += _MD_LINK.findall(line)
        else:
            m = _RST_UNDERLINE.match(line)
            if m and i > 0 and lines[i - 1].strip() and len(line.rstrip()) >= len(lines[i - 1].rstrip()):
                char = m.group(1)
                if char not in rst_levels:
                    rst_levels.append(char)
                heads.append((i, rst_levels.index(char) + 1, lines[i - 1].strip()))
            links += re.findall(r"`[^`<]*<([^>`]+)>`_", line)
    sections, stack = [], []   # stack of (level, qualified)
    for n, (line_no, level, title) in enumerate(heads):
        end = len(lines)
        for later_line, later_level, _ in heads[n + 1:]:
            if later_level <= level:
                end = later_line - 1
                break
        while stack and stack[-1][0] >= level:
            stack.pop()
        parent = stack[-1][1] if stack else None
        qualified = f"{parent} > {title}" if parent else title
        sections.append({"name": title, "qualified": qualified, "kind": "section", "line": line_no,
                         "end_line": max(end, line_no), "parent": parent, "level": level})
        stack.append((level, qualified))
    return sections, links


# ------------------------------------------------------------ tsconfig
def _jsonc(text: str):
    """JSON with comments and trailing commas, as tsconfig allows."""
    out, i, n, in_str = [], 0, len(text), False
    while i < n:
        c = text[i]
        if in_str:
            out.append(c)
            if c == "\\" and i + 1 < n:
                out.append(text[i + 1]); i += 1
            elif c == '"':
                in_str = False
        elif c == '"':
            in_str = True; out.append(c)
        elif text.startswith("//", i):
            while i < n and text[i] != "\n":
                i += 1
            continue
        elif text.startswith("/*", i):
            end = text.find("*/", i + 2)
            i = n if end < 0 else end + 2
            continue
        else:
            out.append(c)
        i += 1
    return json.loads(re.sub(r",(\s*[}\]])", r"\1", "".join(out)))


def load_tsconfigs(read, paths: set[str]) -> dict[str, dict]:
    """{directory: {"base": dir for paths, "paths": {pattern: [targets]}}} for every tsconfig in the project."""
    configs = {}

    def options(path: str, seen: set) -> dict:
        if path in seen or path not in paths:
            return {}
        seen.add(path)
        try:
            data = _jsonc(read(path).decode("utf-8", errors="replace"))
        except (ValueError, KeyError):
            return {}
        here = posixpath.dirname(path)
        merged = {}
        ext = data.get("extends")
        if isinstance(ext, str) and ext.startswith("."):
            target = posixpath.normpath(posixpath.join(here, ext))
            merged = options(target if target.endswith(".json") else target + ".json", seen)
        co = data.get("compilerOptions") or {}
        if "baseUrl" in co:
            merged["baseUrl"] = posixpath.normpath(posixpath.join(here, co["baseUrl"]))
        if "paths" in co:
            merged["paths"] = co["paths"]
            merged["paths_dir"] = here
        return merged

    for path in sorted(paths):
        if posixpath.basename(path) == "tsconfig.json":
            o = options(path, set())
            base = o.get("baseUrl") or o.get("paths_dir") or posixpath.dirname(path)
            configs[posixpath.dirname(path)] = {"base": base if base != "." else "",
                                                "baseUrl": o.get("baseUrl"), "paths": o.get("paths") or {}}
    return configs


def _nearest(configs: dict, path: str) -> dict | None:
    configs = {k: v for k, v in configs.items() if k != "__python_roots__"}
    d = posixpath.dirname(path)
    while True:
        if d in configs:
            return configs[d]
        if d in ("", "/"):
            return configs.get("")
        d = posixpath.dirname(d)


class ArtifactIndex:
    def __init__(self, conn_factory, profiles=("generic", "software", "documents")):
        self._connect = conn_factory
        self.profiles = tuple(profiles)
        self.last_update = {"parsed": 0, "reused": 0, "unsupported": 0, "described": 0}
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

    def _parser_for(self, path: str) -> str | None:
        ext = posixpath.splitext(path)[1]
        if ext in LANGUAGES and "software" in self.profiles:
            return LANGUAGES[ext][0]
        if ext.lower() in DOCUMENTS and "documents" in self.profiles:
            return DOCUMENTS[ext.lower()]
        return None

    @staticmethod
    def _parse(parser: str, source: bytes) -> tuple[list, list]:
        if parser in ("python", "typescript", "tsx"):
            deps = parse_python(source) if parser == "python" else parse_typescript(source, parser == "tsx")
            try:
                parts = python_symbols(source) if parser == "python" else \
                    typescript_symbols(source, parser == "tsx")
            except RecursionError:   # pathologically deep code (minified bundles): imports still count
                parts = []
            return deps, parts
        sections, links = document_sections(source, parser)
        return [{"link": link} for link in links], sections

    # ------------------------------------------------------------ update
    def update(self, archive) -> dict:
        """Describe and parse new versions, re-resolve dependencies, and refresh parts and search."""
        conn = self._connect()
        try:
            current = self.current_files(conn)
            parsed = reused = unsupported = described = 0
            conn.execute("BEGIN IMMEDIATE")
            for path, (oid, _) in sorted(current.items()):
                source = None
                if not conn.execute("SELECT 1 FROM artifact_meta WHERE object_id = ?", (oid,)).fetchone():
                    source = archive.get(oid)
                    head = source[:8192]
                    is_text = b"\0" not in head
                    try:
                        head.decode("utf-8")
                    except UnicodeDecodeError as err:
                        is_text = is_text and err.start > len(head) - 4   # a character cut at the boundary
                    conn.execute("INSERT INTO artifact_meta VALUES (?, ?, ?, ?, ?)",
                                 (oid, mimetypes.guess_type(path)[0], len(source), int(is_text),
                                  source.count(b"\n") + (1 if source and not source.endswith(b"\n") else 0)
                                  if is_text else None))
                    described += 1
                parser = self._parser_for(path)
                if parser is None:
                    unsupported += 1
                    continue
                if conn.execute("SELECT 1 FROM artifact_parse WHERE object_id = ? AND parser = ? AND version = ?",
                                (oid, parser, PARSER_VERSION)).fetchone():
                    reused += 1
                    continue
                source = source if source is not None else archive.get(oid)
                deps, parts = self._parse(parser, source)
                conn.execute("INSERT OR REPLACE INTO artifact_parse VALUES (?, ?, ?, ?, ?, ?)",
                             (oid, parser, PARSER_VERSION, json.dumps(deps), json.dumps(parts),
                              datetime.now(timezone.utc).isoformat()))
                parsed += 1
            self._refresh(conn, archive, current)
            conn.execute("COMMIT")
            self.last_update = {"parsed": parsed, "reused": reused, "unsupported": unsupported,
                                "described": described}
            return self.last_update
        except BaseException:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            raise
        finally:
            conn.close()

    def _refresh(self, conn, archive, current) -> None:
        """Rewrite edges and parts for the current versions, and bring search up to date."""
        paths = set(current)
        configs = load_tsconfigs(lambda p: archive.get(current[p][0]), paths) if "software" in self.profiles else {}
        configs["__python_roots__"] = python_roots(paths)
        conn.execute("DELETE FROM code_edges")
        conn.execute("DELETE FROM artifact_parts")
        for path, (oid, _) in sorted(current.items()):
            parser = self._parser_for(path)
            if parser is None:
                continue
            row = conn.execute("SELECT deps, parts FROM artifact_parse WHERE object_id = ? AND parser = ?",
                               (oid, parser)).fetchone()
            if row is None:
                continue
            for target, kind, spec in self._resolve(path, parser, json.loads(row[0]), paths, configs):
                conn.execute("INSERT INTO code_edges VALUES (?, ?, ?, ?)", (path, target, kind, spec))
            for p in json.loads(row[1]):
                conn.execute("INSERT INTO artifact_parts VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                             (path, p["name"], p["qualified"], p["kind"], p["line"], p["end_line"], p["parent"], oid))
        indexed = dict(conn.execute("SELECT path, object_id FROM artifact_fts").fetchall())
        for path, oid in indexed.items():
            if current.get(path, (None,))[0] != oid:
                conn.execute("DELETE FROM artifact_fts WHERE path = ?", (path,))
        for path, (oid, _) in sorted(current.items()):
            if indexed.get(path) == oid:
                continue
            meta = conn.execute("SELECT is_text, size FROM artifact_meta WHERE object_id = ?", (oid,)).fetchone()
            if meta and meta[0] and meta[1] <= FTS_MAX_BYTES:
                body = archive.get(oid).decode("utf-8", errors="replace")
                conn.execute("INSERT INTO artifact_fts VALUES (?, ?, ?)", (path, oid, body))

    def rebuild(self, archive) -> dict:
        conn = self._connect()
        try:
            for table in ("artifact_parse", "artifact_meta", "artifact_parts", "code_edges", "artifact_fts"):
                conn.execute(f"DELETE FROM {table}")
            conn.commit()
        finally:
            conn.close()
        return self.update(archive)

    # ------------------------------------------------------------ resolution
    @staticmethod
    def _resolve(path: str, parser: str, deps: list[dict], paths: set[str], configs: dict):
        """Yield (target path or None, edge type, spec) for each dependency."""
        here = posixpath.dirname(path)
        if parser == "python":
            for imp in deps:
                if imp["level"]:
                    base = here
                    for _ in range(imp["level"] - 1):
                        base = posixpath.dirname(base)
                    stem = posixpath.join(base, *imp["module"].split(".")) if imp["module"] else base
                    candidates = [stem] + [posixpath.join(stem, n) for n in imp["names"]]
                    roots = [""]
                else:
                    stem = posixpath.join(*imp["module"].split("."))
                    candidates = [stem] + [posixpath.join(stem, n) for n in imp["names"]]
                    roots = list(configs.get("__python_roots__", PY_SOURCE_ROOTS))
                hit = False
                spec = imp["module"] or "." * imp["level"]
                for root in roots:
                    for c in candidates:
                        for file in (f"{root}{c}.py", f"{root}{c}/__init__.py"):
                            file = posixpath.normpath(file)
                            if file in paths and file != path:
                                hit = True
                                yield file, "imports", spec
                                # Importing a module runs every parent package's __init__.py.
                                parent = posixpath.dirname(file if not file.endswith("/__init__.py")
                                                           else posixpath.dirname(file))
                                while parent and parent + "/" != root and parent != root.rstrip("/"):
                                    init = f"{parent}/__init__.py"
                                    if init in paths and init != path:
                                        yield init, "imports", spec
                                    parent = posixpath.dirname(parent)
                if not hit:
                    # A relative import is local by definition; an absolute one may be a package.
                    yield None, "unresolved" if imp["level"] else "external", ("." * imp["level"]) + imp["module"]
        elif parser in ("typescript", "tsx"):
            config = _nearest(configs, path)
            for imp in deps:
                spec = imp["spec"]
                if spec.startswith("."):
                    target = _ts_file(posixpath.normpath(posixpath.join(here, spec)), paths)
                    yield target, "imports" if target else "unresolved", spec
                    continue
                aliased, target = _ts_alias(spec, config, paths)
                if target:
                    yield target, "imports", spec
                else:
                    yield None, "unresolved" if aliased else "external", spec
        else:
            for dep in deps:
                link = dep["link"].split("#", 1)[0].split("?", 1)[0]
                if not link or re.match(r"^[a-z][a-z0-9+.-]*:", link, re.I) or link.startswith("/"):
                    continue   # a web or absolute link: not an artifact in this project
                target = posixpath.normpath(posixpath.join(here, link))
                if target in paths:
                    yield target, "links", dep["link"]
                elif target + ".md" in paths:
                    yield target + ".md", "links", dep["link"]

    # ------------------------------------------------------------ queries
    def _edges(self, column: str, value: str, types=("imports",)) -> list[str]:
        conn = self._connect()
        try:
            other = "to_path" if column == "from_path" else "from_path"
            return sorted({r[0] for r in conn.execute(
                f"SELECT {other} FROM code_edges WHERE {column} = ? AND type IN ({','.join('?' * len(types))})",
                (value, *types))})
        finally:
            conn.close()

    def imports_of(self, path: str) -> list[str]:
        return self._edges("from_path", path)

    def importers_of(self, path: str) -> list[str]:
        return self._edges("to_path", path)

    def links_of(self, path: str) -> list[str]:
        return self._edges("from_path", path, ("links",))

    def linked_from(self, path: str) -> list[str]:
        return self._edges("to_path", path, ("links",))

    def closure(self, paths, direction: str = "dependencies", types=("imports",)) -> set[str]:
        """Files reachable by dependencies (or by being depended on), including the start."""
        column = "from_path" if direction == "dependencies" else "to_path"
        seen, stack = set(paths), list(paths)
        while stack:
            for nxt in self._edges(column, stack.pop(), types):
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

    def unresolved(self, paths) -> dict[str, list[str]]:
        """Local imports that name no file, for each of these paths that has any."""
        conn = self._connect()
        try:
            out: dict[str, list[str]] = {}
            for path in sorted(paths):
                specs = [r[0] for r in conn.execute(
                    "SELECT spec FROM code_edges WHERE from_path = ? AND type = 'unresolved'", (path,))]
                if specs:
                    out[path] = sorted(specs)
            return out
        finally:
            conn.close()

    def parts(self, path: str) -> list[dict]:
        conn = self._connect()
        try:
            return [dict(zip(("name", "qualified", "kind", "line", "end_line", "parent"), r)) for r in conn.execute(
                "SELECT name, qualified, kind, line, end_line, parent FROM artifact_parts WHERE path = ? "
                "ORDER BY line, rowid", (path,))]
        finally:
            conn.close()

    def find_part(self, name: str, kind: str | None = None) -> list[dict]:
        """Parts named `name` (or whose qualified name is `name`, or ends with `.name`), across all artifacts."""
        conn = self._connect()
        try:
            sql = ("SELECT path, name, qualified, kind, line, end_line, parent FROM artifact_parts "
                   "WHERE (name = ? OR qualified = ? OR qualified LIKE ? ESCAPE '\\')")
            like = "%." + name.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            args = [name, name, like]
            if kind:
                sql += " AND kind = ?"
                args.append(kind)
            keys = ("path", "name", "qualified", "kind", "line", "end_line", "parent")
            return [dict(zip(keys, r)) for r in conn.execute(sql + " ORDER BY path, line", args)]
        finally:
            conn.close()

    def metadata(self, object_id: str) -> dict | None:
        conn = self._connect()
        try:
            row = conn.execute("SELECT media_type, size, is_text, lines FROM artifact_meta WHERE object_id = ?",
                               (object_id,)).fetchone()
            return None if row is None else {"media_type": row[0], "size": row[1], "is_text": bool(row[2]),
                                             "lines": row[3]}
        finally:
            conn.close()

    def search(self, query: str, limit: int = 20) -> list[dict]:
        """Full-text search over current text artifacts: path, a short snippet, and rank (lower is better)."""
        conn = self._connect()
        try:
            terms = " ".join('"' + t.replace('"', '""') + '"' for t in query.split())
            if not terms:
                return []
            return [{"path": p, "snippet": s, "rank": r} for p, s, r in conn.execute(
                "SELECT path, snippet(artifact_fts, 2, '[', ']', ' ... ', 12), rank FROM artifact_fts "
                "WHERE artifact_fts MATCH ? ORDER BY rank LIMIT ?", (terms, limit))]
        finally:
            conn.close()


def _ts_file(stem: str, paths: set[str]) -> str | None:
    options = [stem] + [stem + ext for ext in TS_EXTENSIONS] + \
              [posixpath.join(stem, "index" + ext) for ext in TS_EXTENSIONS]
    # TypeScript imports name the emitted .js file; map it back to the .ts source.
    if stem.endswith(".js"):
        options += [stem[:-3] + ".ts", stem[:-3] + ".tsx"]
    return next((posixpath.normpath(o) for o in options if posixpath.normpath(o) in paths), None)


def _ts_alias(spec: str, config: dict | None, paths: set[str]) -> tuple[bool, str | None]:
    """(matched an alias, resolved file) for a non-relative TypeScript import."""
    if not config:
        return False, None
    base = config["base"]
    for pattern, targets in config["paths"].items():
        if "*" in pattern:
            prefix, _, suffix = pattern.partition("*")
            if not (spec.startswith(prefix) and spec.endswith(suffix) and len(spec) >= len(prefix) + len(suffix)):
                continue
            star = spec[len(prefix):len(spec) - len(suffix)]
        elif spec != pattern:
            continue
        else:
            star = ""
        for t in targets:
            found = _ts_file(posixpath.normpath(posixpath.join(base, t.replace("*", star))), paths)
            if found:
                return True, found
        return True, None
    if config.get("baseUrl") is not None:
        found = _ts_file(posixpath.normpath(posixpath.join(config["baseUrl"], spec)), paths)
        if found:
            return True, found
    return False, None


CodeGraph = ArtifactIndex   # the name used before Stage 2.7
