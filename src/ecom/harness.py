"""SQLite test harness for the dbt project. It is a test tool, not a dbt replacement.

It renders the project's own model, snapshot and test files with Jinja, using a small subset of
dbt's context: ``ref``, ``source``, ``config``, ``var``, ``this``, ``is_incremental``, ``target`` and
``adapter.dispatch``. It then runs them on SQLite in dependency order. Because every
dialect-specific expression goes through a dispatched macro, the harness runs the same SQL text that
dbt-duckdb runs, apart from the ``sqlite__`` macro bodies.

What it supports, and nothing more:

* materializations: view, table, incremental (``delete+insert`` on ``unique_key``)
* snapshots: ``timestamp`` strategy (SCD2 with dbt_valid_from / dbt_valid_to / dbt_updated_at)
* generic tests: unique, not_null, accepted_values, relationships, plus the project's custom
  ``{% test %}`` blocks; singular tests; ``severity: warn``

CI runs the real thing (``dbt build`` on DuckDB) and compares the marts with this harness's output.
"""
from __future__ import annotations

import csv
import re
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from jinja2 import Environment, StrictUndefined

REF_RX = re.compile(r"""ref\(\s*['"](\w+)['"]\s*\)""")
SNAPSHOT_RX = re.compile(r"{%-?\s*snapshot\s+(\w+)\s*-?%}(.*?){%-?\s*endsnapshot\s*-?%}", re.S)
TEST_BLOCK_RX = re.compile(r"{%-?\s*test\s+(\w+)\s*\((.*?)\)\s*-?%}(.*?){%-?\s*endtest\s*-?%}", re.S)


class HarnessError(RuntimeError):
    pass


@dataclass
class Node:
    name: str
    kind: str                      # model | snapshot
    path: Path
    sql: str
    layer: str
    config: dict = field(default_factory=dict)
    deps: set = field(default_factory=set)


@dataclass
class TestResult:
    name: str
    target: str
    layer: str
    severity: str
    failures: int

    @property
    def status(self) -> str:
        if self.failures == 0:
            return "pass"
        return "warn" if self.severity == "warn" else "fail"


class _Adapter:
    def __init__(self, lib_getter, adapter_type: str):
        self._lib = lib_getter
        self.type = adapter_type

    def dispatch(self, name: str, macro_namespace: str | None = None):
        lib = self._lib()
        for candidate in (f"{self.type}__{name}", f"default__{name}"):
            if hasattr(lib, candidate):
                return getattr(lib, candidate)
        raise HarnessError(f"no {self.type}__ or default__ implementation for macro {name}")


class Target:
    def __init__(self, adapter_type: str):
        self.type = adapter_type
        self.schema = "main"
        self.name = "harness"


class Project:
    """Reads dbt_project.yml, models, snapshots, macros, schema YAML and tests from a dbt project folder."""

    def __init__(self, root: str | Path, adapter_type: str = "sqlite", vars: dict | None = None):
        self.root = Path(root)
        cfg = yaml.safe_load((self.root / "dbt_project.yml").read_text())
        self.name = cfg["name"]
        self.vars = {**cfg.get("vars", {}), **(vars or {})}
        self.folder_config = cfg.get("models", {}).get(self.name, {})
        self.adapter_type = adapter_type
        self.target = Target(adapter_type)
        self._lib = None
        self.env = Environment(undefined=StrictUndefined, extensions=["jinja2.ext.do"])
        self.env.globals.update({
            "var": self._var, "adapter": _Adapter(lambda: self._lib, adapter_type), "target": self.target,
            "return": lambda x: x, "log": lambda *a, **k: "", "exceptions": None,
        })
        self._lib = self.env.from_string(self._macro_source()).module
        self.nodes: dict[str, Node] = {}
        self._load_models()
        self._load_snapshots()
        self.sources = self._load_sources()
        self.schema_tests = self._load_schema_tests()

    # ------------------------------------------------------------------ loading
    def _var(self, name, default=None):
        if name in self.vars:
            return self.vars[name]
        if default is None:
            raise HarnessError(f"var {name!r} is not defined")
        return default

    def _macro_source(self) -> str:
        parts = []
        for path in sorted((self.root / "macros").rglob("*.sql")):
            parts.append(path.read_text())
        for path in sorted((self.root / "tests" / "generic").glob("*.sql")):
            text = path.read_text()
            parts.append(TEST_BLOCK_RX.sub(lambda m: "{% macro test_" + m.group(1) + "(" + m.group(2) + ") %}"
                                           + m.group(3) + "{% endmacro %}", text))
        return "\n".join(parts)

    def macros(self) -> dict:
        return {k: getattr(self._lib, k) for k in dir(self._lib) if not k.startswith("_")}

    def _folder_defaults(self, rel: Path) -> dict:
        cfg: dict = {}
        node = self.folder_config
        for c in {k[1:]: v for k, v in node.items() if k.startswith("+")}.items():
            cfg[c[0]] = c[1]
        for part in rel.parts[:-1]:
            node = node.get(part, {}) if isinstance(node, dict) else {}
            cfg.update({k[1:]: v for k, v in node.items() if k.startswith("+")})
        return cfg

    def _load_models(self) -> None:
        for path in sorted((self.root / "models").rglob("*.sql")):
            rel = path.relative_to(self.root / "models")
            sql = path.read_text()
            node = Node(name=path.stem, kind="model", path=path, sql=sql, layer=rel.parts[0],
                        config=self._folder_defaults(rel), deps=set(REF_RX.findall(sql)))
            self.nodes[node.name] = node

    def _load_snapshots(self) -> None:
        for path in sorted((self.root / "snapshots").glob("*.sql")):
            for name, body in SNAPSHOT_RX.findall(path.read_text()):
                self.nodes[name] = Node(name=name, kind="snapshot", path=path, sql=body, layer="snapshots",
                                        deps=set(REF_RX.findall(body)))

    def _load_sources(self) -> dict[tuple[str, str], str]:
        out = {}
        for path in (self.root / "models").rglob("*.yml"):
            doc = yaml.safe_load(path.read_text()) or {}
            for src in doc.get("sources", []):
                for t in src.get("tables", []):
                    out[(src["name"], t["name"])] = t.get("identifier", t["name"])
        return out

    def _load_schema_tests(self) -> list[dict]:
        tests = []

        def collect(target_kind, target, layer, columns, model_tests):
            for t in model_tests or []:
                tests.append(_test_spec(t, target_kind, target, layer, None))
            for col in columns or []:
                for t in col.get("data_tests", col.get("tests", [])) or []:
                    tests.append(_test_spec(t, target_kind, target, layer, col["name"]))

        for path in sorted((self.root / "models").rglob("*.yml")):
            doc = yaml.safe_load(path.read_text()) or {}
            for m in doc.get("models", []):
                layer = self.nodes[m["name"]].layer if m["name"] in self.nodes else "models"
                collect("model", m["name"], layer, m.get("columns"), m.get("data_tests", m.get("tests")))
            for src in doc.get("sources", []):
                for t in src.get("tables", []):
                    collect("source", (src["name"], t["name"]), "sources", t.get("columns"),
                            t.get("data_tests", t.get("tests")))
        return tests

    # ------------------------------------------------------------------ rendering
    def relation(self, name: str) -> str:
        if name not in self.nodes:
            raise HarnessError(f"ref to unknown model {name!r}")
        return name

    def source_relation(self, source: str, table: str) -> str:
        try:
            return self.sources[(source, table)]
        except KeyError:
            raise HarnessError(f"unknown source {source}.{table}") from None

    def render(self, sql: str, this: str | None = None, incremental: bool = False,
               captured: dict | None = None, **extra) -> str:
        captured = captured if captured is not None else {}

        def config(**kw):
            captured.update(kw)
            return ""

        ctx = {**self.macros(), "ref": self.relation, "source": self.source_relation, "config": config,
               "this": this, "is_incremental": lambda: incremental, **extra}
        return self.env.from_string(sql).render(**ctx)

    def order(self) -> list[str]:
        """Topological order of models and snapshots (Kahn's algorithm, ties alphabetical)."""
        deps = {n: {d for d in node.deps if d in self.nodes} for n, node in self.nodes.items()}
        missing = {d for node in self.nodes.values() for d in node.deps if d not in self.nodes}
        if missing:
            raise HarnessError(f"ref to unknown model(s): {sorted(missing)}")
        out, ready = [], sorted(n for n, d in deps.items() if not d)
        while ready:
            n = ready.pop(0)
            out.append(n)
            for m, d in deps.items():
                if n in d:
                    d.discard(n)
                    if not d and m not in out and m not in ready:
                        ready.append(m)
            ready.sort()
        if len(out) != len(self.nodes):
            raise HarnessError("dependency cycle between models")
        return out


def _test_spec(t, target_kind, target, layer, column) -> dict:
    if isinstance(t, str):
        name, args = t, {}
    else:
        name, args = next(iter(t.items()))
        args = dict(args or {})
    cfg = args.pop("config", {}) or {}
    return {"name": name, "args": args, "severity": cfg.get("severity", "error"), "target_kind": target_kind,
            "target": target, "layer": layer, "column": column}


class SqliteRunner:
    def __init__(self, project: Project, db: str | Path = ":memory:"):
        self.project = project
        self.conn = sqlite3.connect(str(db))
        self.timings: dict[str, float] = {}
        self.incremental_rows: dict[str, int] = {}

    # ------------------------------------------------------------------ seeds
    def seed(self, seeds_dir: str | Path) -> dict[str, int]:
        counts = {}
        for path in sorted(Path(seeds_dir).glob("*.csv")):
            with path.open(newline="") as f:
                rows = list(csv.reader(f))
            header, data = rows[0], rows[1:]
            name = path.stem
            self.conn.execute(f'drop table if exists "{name}"')
            self.conn.execute(f'create table "{name}" ({", ".join(f"{c} text" for c in header)})')
            self.conn.executemany(f'insert into "{name}" values ({", ".join("?" for _ in header)})',
                                  [[v if v != "" else None for v in r] for r in data])
            counts[name] = len(data)
        self.conn.commit()
        return counts

    # ------------------------------------------------------------------ models
    def _exists(self, name: str) -> str | None:
        row = self.conn.execute("select type from sqlite_master where name = ?", (name,)).fetchone()
        return row[0] if row else None

    def _drop(self, name: str) -> None:
        kind = self._exists(name)
        if kind:
            self.conn.execute(f'drop {kind} "{name}"')

    def run_model(self, node: Node, full_refresh: bool = False) -> None:
        captured = dict(node.config)
        self.project.render(node.sql, this=node.name, incremental=False, captured=captured)   # reads config()
        mat = captured.get("materialized", "view")
        is_inc = mat == "incremental" and not full_refresh and self._exists(node.name) == "table"
        sql = self.project.render(node.sql, this=node.name, incremental=is_inc, captured={})
        start = time.perf_counter()
        if mat == "view":
            self._drop(node.name)
            self.conn.execute(f'create view "{node.name}" as {sql}')
        elif mat == "table" or (mat == "incremental" and not is_inc):
            self._drop(node.name)
            self.conn.execute(f'create table "{node.name}" as {sql}')
        elif mat == "incremental":
            key = captured.get("unique_key")
            if not key:
                raise HarnessError(f"{node.name}: incremental model needs unique_key")
            self.conn.execute('drop table if exists "__incr"')
            self.conn.execute(f'create temp table "__incr" as {sql}')
            self.incremental_rows[node.name] = self.conn.execute('select count(*) from "__incr"').fetchone()[0]
            self.conn.execute(f'delete from "{node.name}" where {key} in (select {key} from "__incr")')
            self.conn.execute(f'insert into "{node.name}" select * from "__incr"')
            self.conn.execute('drop table "__incr"')
        else:
            raise HarnessError(f"{node.name}: unsupported materialization {mat}")
        self.conn.commit()
        self.timings[node.name] = time.perf_counter() - start

    def run_snapshot(self, node: Node) -> dict:
        captured: dict = {}
        sql = self.project.render(node.sql, captured=captured)
        if captured.get("strategy") != "timestamp":
            raise HarnessError(f"{node.name}: only the timestamp strategy is supported")
        key, upd = captured["unique_key"], captured["updated_at"]
        self.conn.execute('drop table if exists "__snap_src"')
        self.conn.execute(f'create temp table "__snap_src" as {sql}')
        cols = [r[1] for r in self.conn.execute('pragma table_info("__snap_src")')]
        col_list = ", ".join(cols)
        if self._exists(node.name) != "table":
            self.conn.execute(f'create table "{node.name}" as select {col_list}, {upd} as dbt_updated_at, '
                              f'{upd} as dbt_valid_from, cast(null as text) as dbt_valid_to from "__snap_src"')
            inserted, closed = self.conn.execute(f'select count(*) from "{node.name}"').fetchone()[0], 0
        else:
            changed = (f'select s.{key} as k, s.{upd} as u from "__snap_src" s join "{node.name}" t '
                       f'on s.{key} = t.{key} and t.dbt_valid_to is null where s.{upd} > t.dbt_updated_at')
            rows = self.conn.execute(changed).fetchall()
            for k, u in rows:
                self.conn.execute(f'update "{node.name}" set dbt_valid_to = ? where {key} = ? and dbt_valid_to is null',
                                  (u, k))
            new = self.conn.execute(
                f'insert into "{node.name}" select {col_list}, {upd}, {upd}, null from "__snap_src" s '
                f'where not exists (select 1 from "{node.name}" t where t.{key} = s.{key} and t.dbt_valid_to is null)')
            inserted, closed = new.rowcount, len(rows)
        self.conn.execute('drop table "__snap_src"')
        self.conn.commit()
        return {"inserted": inserted, "closed": closed}

    # ------------------------------------------------------------------ tests
    def _test_sql(self, spec: dict) -> str:
        p = self.project
        if spec["target_kind"] == "model":
            model = p.relation(spec["target"])
        else:
            model = p.source_relation(*spec["target"])
        col, args, name = spec["column"], spec["args"], spec["name"]
        if name == "unique":
            return f"select {col} from {model} where {col} is not null group by {col} having count(*) > 1"
        if name == "not_null":
            return f"select * from {model} where {col} is null"
        if name == "accepted_values":
            quote = args.get("quote", True)
            vals = ", ".join(f"'{v}'" if quote else str(v) for v in args["values"])
            return f"select * from {model} where {col} not in ({vals})"
        if name == "relationships":
            to = p.render("{{ " + args["to"] + " }}")
            return (f"select child.{col} from {model} child left join {to} parent "
                    f"on child.{col} = parent.{args['field']} where child.{col} is not null "
                    f"and parent.{args['field']} is null")
        macro = p.macros().get(f"test_{name}")
        if macro is None:
            raise HarnessError(f"unknown generic test {name}")
        kwargs = dict(args)
        if col is not None:
            kwargs["column_name"] = col
        return str(macro(model=model, **kwargs))

    def run_tests(self) -> list[TestResult]:
        results = []
        for spec in self.project.schema_tests:
            sql = self._test_sql(spec)
            n = self.conn.execute(f"select count(*) from ({sql})").fetchone()[0]
            target = spec["target"] if isinstance(spec["target"], str) else ".".join(spec["target"])
            label = f"{spec['name']}({spec['column']})" if spec["column"] else spec["name"]
            results.append(TestResult(label, target, spec["layer"], spec["severity"], n))
        for path in sorted((self.project.root / "tests").glob("*.sql")):
            sql = self.project.render(path.read_text())
            n = self.conn.execute(f"select count(*) from ({sql})").fetchone()[0]
            results.append(TestResult(path.stem, "singular", "singular", "error", n))
        return results

    # ------------------------------------------------------------------ build
    def build(self, full_refresh: bool = False) -> dict:
        snapshots = {}
        for name in self.project.order():
            node = self.project.nodes[name]
            if node.kind == "snapshot":
                snapshots[name] = self.run_snapshot(node)
            else:
                self.run_model(node, full_refresh=full_refresh)
        tests = self.run_tests()
        return {"snapshots": snapshots, "tests": tests,
                "rows": {n: self.count(n) for n in self.project.nodes}}

    def count(self, name: str) -> int:
        return self.conn.execute(f'select count(*) from "{name}"').fetchone()[0]

    def query(self, sql: str) -> list[dict]:
        cur = self.conn.execute(sql)
        cols = [c[0] for c in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]
