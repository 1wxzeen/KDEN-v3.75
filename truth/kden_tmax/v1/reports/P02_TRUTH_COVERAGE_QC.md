# P02 Truth Coverage and QC

Status: complete for `KDEN_V375_TRUTH_EVIDENCE_V1`

The self-contained truth package lives at `truth/kden_tmax/v1/`.

## Coverage

- R14 target dates: 2080 (2021-01-01 through 2026-09-11)
- Development dates: 1710
- Development labels available for supervised use: 1707
- Sealed final-holdout dates: 365
- Post-holdout tail dates: 5
- Tail labels available for post-freeze final scoring: 5

## Evidence-status counts

```json
{
  "audited": 1705,
  "audited_guarded_exception": 2,
  "sealed_holdout": 365,
  "tail_audited": 5,
  "unresolved": 3
}
```

The 365-day holdout was represented only by its fixed date range and verified
Parquet metadata. Its outcome values were not read or placed in the catalog.
Truth columns remain physically separate from the weather-feature substrate.
