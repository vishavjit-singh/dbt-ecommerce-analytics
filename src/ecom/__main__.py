"""``python -m ecom <command>``: generator, SQLite test harness, charts and engine comparison."""
from __future__ import annotations

import json
import shutil
from pathlib import Path

import click

ROOT = Path(__file__).resolve().parents[2]


@click.group()
def cli():
    """Tools around the dbt project (the dbt project itself runs with `dbt`)."""


@cli.command()
@click.option("--batch", type=click.Choice(["1", "2"]), default="2", help="Which delivery to write.")
@click.option("--out", default=str(ROOT / "seeds"), type=click.Path(file_okay=False))
def generate(batch, out):
    """Write the synthetic raw extracts as dbt seeds."""
    from .generate import generate as gen

    out = Path(out)
    if out.exists():
        for f in out.glob("raw_*.csv"):
            f.unlink()
    counts, truth = gen(out, batch=int(batch))
    click.echo(f"batch {batch}: {counts}")
    click.echo(f"injected defects: {truth.defects}")


@cli.command()
@click.option("--db", default=str(ROOT / "target" / "harness.sqlite"), type=click.Path(dir_okay=False))
def harness(db):
    """Run both deliveries through the SQLite test harness (seed → build → seed → build)."""
    from .demo import run_demo

    out = run_demo(ROOT, ROOT / "seeds", Path(db))
    b2 = out["batches"][-1]
    failing = [t for t in b2["tests"] if t["status"] == "fail"]
    click.echo(f"models built: {len(b2['model_rows'])} · tests: {len(b2['tests'])} · failing: {len(failing)} · "
               f"incremental == full refresh: {out['incremental_equals_full_refresh']}")
    for t in failing:
        click.echo(f"  FAIL {t['target']} {t['name']}: {t['failures']}")
    if failing or not out["incremental_equals_full_refresh"]:
        raise SystemExit(1)


@cli.command()
@click.option("--db", default=str(ROOT / "target" / "harness.sqlite"), type=click.Path(exists=True))
@click.option("--out", default=str(ROOT / "docs" / "images"), type=click.Path(file_okay=False))
def report(db, out):
    """Charts from the marts (SQLite harness file or the dbt-duckdb .duckdb file)."""
    from .report import render_all

    for p in render_all(ROOT, Path(db), Path(out)):
        click.echo(f"wrote {p}")


@cli.command()
@click.option("--db", default=str(ROOT / "target" / "harness.sqlite"), type=click.Path(exists=True))
def summary(db):
    """Numbers quoted in the README, computed from the marts."""
    from .report import summary as s

    click.echo(json.dumps(s(Path(db)), indent=2, default=str))


@cli.command()
@click.option("--duckdb", "duck", default=str(ROOT / "target" / "ecommerce.duckdb"), type=click.Path(exists=True))
@click.option("--sqlite", "lite", default=str(ROOT / "target" / "harness.sqlite"), type=click.Path(exists=True))
def compare(duck, lite):
    """Compare the marts built by dbt-duckdb with the SQLite harness's (used in CI)."""
    from .compare import compare_marts

    problems = compare_marts(Path(duck), Path(lite))
    for p in problems:
        click.echo(f"MISMATCH {p}")
    click.echo("marts match" if not problems else f"{len(problems)} mismatches")
    if problems:
        raise SystemExit(1)


@cli.command()
def clean():
    """Remove generated seeds and harness output."""
    for f in (ROOT / "seeds").glob("raw_*.csv"):
        f.unlink()
    shutil.rmtree(ROOT / "target", ignore_errors=True)


if __name__ == "__main__":
    cli()
