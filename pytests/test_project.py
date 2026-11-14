"""Static checks on the dbt project files: things dbt would only report at run time."""
import re
from pathlib import Path

import yaml

from ecom.generate import TABLES
from ecom.harness import Project

ROOT = Path(__file__).resolve().parents[1]


def model_docs():
    out = {}
    for path in (ROOT / "models").rglob("*.yml"):
        doc = yaml.safe_load(path.read_text()) or {}
        for m in doc.get("models", []):
            out[m["name"]] = m
    return out


def test_every_model_is_documented_and_tested():
    docs = model_docs()
    for name, node in Project(ROOT).nodes.items():
        if node.kind != "model":
            continue
        assert name in docs, f"{name} has no YAML entry"
        assert docs[name].get("description"), f"{name} has no description"
        tests = [t for c in docs[name].get("columns", []) for t in c.get("data_tests", [])]
        assert tests or docs[name].get("data_tests"), f"{name} has no tests"


def test_doc_blocks_exist():
    blocks = set(re.findall(r"{%\s*docs\s+(\w+)\s*%}", (ROOT / "models" / "docs.md").read_text()))
    used = set()
    for path in (ROOT / "models").rglob("*.yml"):
        used |= set(re.findall(r"doc\('(\w+)'\)", path.read_text()))
    assert used and used <= blocks


def test_every_dispatched_macro_has_both_implementations():
    text = "\n".join(p.read_text() for p in (ROOT / "macros").glob("*.sql"))
    for name in re.findall(r"adapter\.dispatch\('(\w+)'\)", text):
        assert f"duckdb__{name}" in text and f"sqlite__{name}" in text, name


def test_seed_column_types_match_the_generator():
    """dbt seed would infer types for any column missing here; staging expects text everywhere."""
    seeds = yaml.safe_load((ROOT / "dbt_project.yml").read_text())["seeds"]["ecommerce_analytics"]
    for table, cols in TABLES.items():
        assert list(seeds[table]["+column_types"]) == cols, table


def test_sources_point_at_seeds():
    doc = yaml.safe_load((ROOT / "models" / "staging" / "_sources.yml").read_text())
    identifiers = {t["identifier"] for s in doc["sources"] for t in s["tables"]}
    assert identifiers == set(TABLES)


def test_exposure_refs_exist():
    names = set(Project(ROOT).nodes)
    doc = yaml.safe_load((ROOT / "models" / "exposures.yml").read_text())
    for e in doc["exposures"]:
        for d in e["depends_on"]:
            assert re.search(r"ref\('(\w+)'\)", d).group(1) in names
