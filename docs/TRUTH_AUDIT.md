# KDEN Tmax: why the label needed an audit

The modeling target is KDEN's official daily maximum temperature in degrees
Fahrenheit, not the highest HRRR forecast and not a maximum reconstructed from
the project's observation feed. The climate day is the fixed right-open
interval `[07Z on date d, 07Z on date d+1)`; this is distinct from a DST-changing
midnight-to-midnight civil day.

## The problem with accepting one parsed row

IEM's daily endpoint supplied convenient numeric candidates. Its underlying
NWS CLI/CF6 report histories could disagree with the candidate or with each
other. A later malformed or stale-heading report could associate another
day's value with the requested date. That did not make every IEM value wrong;
it meant a parsed candidate was not, by itself, an audited outcome.

Two documented non-reserved examples illustrate the difference:

| Target date | Original parsed candidate | Audited outcome |
|---|---:|---:|
| 2021-01-20 | 39°F | 59°F |
| 2022-04-18 | 80°F | 65°F |

Both corrections were supported by the completed CLI and CF6 evidence and
recorded as guarded exceptions, rather than silent edits to original files.
These examples are not a claim that every disagreement can be resolved.

## Reuse rather than a second, incompatible truth pipeline

v3.75 adopted a byte-preserved copy of the already-audited Stage 5R.1 package
from the earlier project, together with its rule configuration, exception
evidence, manifests, and report chronology. It did not import that project's
Python package at runtime. Five additional dates were acquired and audited
separately. The local working release was self-contained; individual truth
tables and raw reports are not redistributed in this public source release.

The adopted decision procedure keeps the first completed CLI after the climate
day closes and the later eligible CLI/CF6 chronology. Automatic acceptance
requires both report families and unanimity across eligible values. An explicit
guarded exception must match its expected evidence. Unresolved disagreements
remain unresolved—never imputed merely to increase sample size. The original
candidate, source identifiers, chronology, corrections, and QC status remain
provenance rather than forecast features.

## Coverage in the accepted local package

- Weather study: 2021-01-01–2026-09-11, 2,080 target days.
- Development: 1,710 days, with 1,707 accepted labels and three unresolved dates.
- Reserved interval: 2025-09-07–2026-09-06, 365 days. Its historical sealed status
  is not evidence that the full interval is a new, project-wide blind test.
- Additional accepted dates: 2026-09-07–2026-09-11. These five were treated as
  truth in the adopted contract; no pending-maturity exclusion was imposed.

The original protocol allowed a 62-day later-correction horizon. The owner chose
to proceed before every recent date had exhausted that horizon, preserving
provenance rather than withholding otherwise accepted labels. That is an
explicit policy choice, not a guarantee that an official report can never be
corrected later.

Predictors are built independently. Authorized fitting/scoring joins use target
date and accepted non-null audited outcomes. All issues from one day stay in
the same fold; label values, report chronology, and truth status are never
predictors. Missing labels are excluded from supervised loss/scoring without
deleting their weather rows.

## Trace the implementation

- [P02 coverage and QC](../truth/kden_tmax/v1/reports/P02_TRUTH_COVERAGE_QC.md)
- [Truth adoption code](../src/kden_v375/prefit/p02_truth.py)
- [Auditing rules](../src/kden_v375/prefit/p02_rules.py)
- [Focused rule/adoption tests](../tests/unit/test_prefit_p02_truth.py)
- [P02 historical acceptance metadata](../state/PREFIT_P02_PASS.json)

This guide replaces a public link to an older truth-layer PDF. That original
PDF is not included because it contains individual reserved-period outcomes
and superseded source/fallback discussion. It was not silently rewritten.
This page describes the project target; it is not current advice about the
settlement rules of any particular market contract.
