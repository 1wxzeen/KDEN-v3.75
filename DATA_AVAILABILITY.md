# What is—and is not—in this repository

This is a source-and-evidence release, not a distribution of the complete local
forecast archive. The original accepted weather release covers 2021-01-01
through 2026-09-11. A fresh clone does not contain its 118,536 feature rows or
8,919,598 trajectory references as data tables.

## Included

- Acquisition, reader, prefit, model-comparison, and experimental source code;
  tests; scientific specifications and versioned configurations.
- Selected aggregate comparison reports, scorecards, population summaries,
  acceptance metadata, and four front-page figures with editable/replotting
  sources. The figure inputs contain aggregates, not individual labels.
- Five research reading editions with original source identities and explicit
  public-edit provenance. Historical instructions are not current run status.
- Metadata describing frozen releases. A saved acceptance record refers to
  the original complete local release; it does not certify that a clone
  contains those omitted files or can pass that original acceptance scan.

## Not bundled

The following are deliberately excluded:

- Weather Parquet archives, feature/trajectory partitions, raw GRIB payloads,
  caches, and the thousands of supporting acquisition receipts.
- The adopted CLI/CF6 truth package, raw climate reports, daily outcome tables,
  and reserved-outcome packages. The audit method, coverage counts, and safe
  historical correction examples are documented in [the truth guide](docs/TRUTH_AUDIT.md).
- Individual predictions, fitted model arrays, neural weights, virtual
  environments, machine-specific install logs, credentials, and backups.
- Most run artifacts and the full 122-figure S5 diagnostic archive. Only
  diagnostics embedded in its retained report and the curated public figures
  are shipped. Some old run references are explicitly marked “Not bundled.”
- Earlier codebases as runtime dependencies. Historical source was a reference
  during development; the public package does not import a sibling project.

These exclusions are packaging choices, not assertions that NOAA or IEM have
no source data. Archive availability and original publication timing are
separate from what this repository redistributes.

## Reproduction boundary

The [quickstart](examples/quickstart.py), public figure tests, and figure
renderers operate on bundled evidence. Full scientific reproduction requires
the omitted archives, receipts, labels, and stage-specific environments; simply
creating empty files at their paths is not a substitute. Historical frozen
hashes must not be rewritten to make a reduced public checkout appear complete.

No automatic downloader or expensive model replay is run by the public
quickstart. Reacquisition, label adoption, or model fitting is a separate,
deliberate workflow. Public source configurations describe those workflows but
do not promise that every historical external source or model weight remains
available unchanged.
