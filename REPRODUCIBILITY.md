# Reproducing the public evidence

The commands below are short checks and replotting, not acquisition or training.
Run them from the repository root. Python 3.12 is the version used by this
project; no shell variables or previously activated environment are assumed.

## 1. Inspect and validate bundled aggregates

```sh
python3.12 examples/quickstart.py
python3.12 -m unittest discover -s publication/figures -p 'test_*.py'
python3.12 tools/check_publication.py
```

These use the standard library. They check the public package and saved figure
inputs, not raw prediction pages or the original full-release acceptance gates.
The manifest hashes public bytes separately from original source identities.

## 2. Replot the statistical figures

```sh
python3.12 -m venv .venv-public
.venv-public/bin/python -m pip install -r requirements-public.txt
.venv-public/bin/python publication/figures/render_overall_scorecard.py --output-dir /tmp/kden-public-figures
.venv-public/bin/python publication/figures/render_issue_time.py --output-dir /tmp/kden-public-figures
.venv-public/bin/python publication/figures/render_confidence_reliability.py --output-dir /tmp/kden-public-figures
.venv-public/bin/python publication/figures/render_mathematical_illustrations.py --output-dir /tmp/kden-public-figures
```

The empirical renderers use bundled aggregate scorecards/compact JSON; they do not fit,
rescore individuals, or download anything. Output goes outside the accepted
public evidence by default or to the explicit directory above. Matplotlib and
font/platform versions can affect image bytes; matching inputs and numerical
values is the important invariant. The committed PNG/SVG files are the reviewed
publication images.

The mathematical illustrations use only explicit synthetic parameters. They
explain residual transfer and distribution shape; they are not KDEN forecasts
or measured performance. Their renderer also writes a small algebra-check
record and defaults to a temporary output directory. See the
[mathematical companion](docs/MATHEMATICAL_SYSTEMS.md) and
[illustration notes](publication/figures/README.md#mathematical-illustrations).

`publication/figures/system_overview.svg` is the editable system diagram. Open
it in an SVG-capable viewer; the committed PNG is the README preview. If
`rsvg-convert` is installed, a preview can be exported with:

```sh
rsvg-convert -o /tmp/kden-system-overview.png publication/figures/system_overview.svg
```

See [the figure guide](publication/figures/README.md) for cohorts, scoring
conventions, support differences, confidence rules, and source hashes.

## 3. Inspect a small piece of the acquisition foundation

This optional environment installs the original acquisition/reader dependencies,
not the experiment-specific ML stacks:

```sh
python3.12 -m venv .venv-core
.venv-core/bin/python -m pip install .
.venv-core/bin/python examples/clock_demo.py
.venv-core/bin/python -m unittest tests.unit.test_atomic tests.unit.test_http_range
```

The demo constructs two issue grids; the HTTP tests use a fake transport, not
NOAA. They are intentionally bounded. Do not replace these commands with an
unreviewed full test/replay invocation: historical integration tests can require
omitted local data or expensive scans.

## Full study versus public evidence

The numerical studies were executed historically. This release preserves
selected saved evidence and source; it does not supply a fully replayable data
snapshot. Full replication requires the archives and contracts described in
[DATA_AVAILABILITY.md](DATA_AVAILABILITY.md), plus each experiment's separate
dependency environment. Historical reports retain the selection-timing defect
and sensitivity qualification. Replotting does not turn those assessments into
a new blind test or establish trading profitability.
