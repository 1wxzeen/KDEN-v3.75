"""Truth-free HRRR transform; context medians are never fitted on queries."""
from __future__ import annotations

import calendar
import json
import math
from datetime import UTC, date, datetime, timedelta
from statistics import median
from zoneinfo import ZoneInfo

from .common import ContractError, check_document, digest, inside, read_json
from .dates import label_cutoff, parse_date, role

DENVER = ZoneInfo("America/Denver")
SPINE = "universal_issue_state/v1/issue_spine/issue_spine.parquet"
CYCLES = "universal_issue_state/v1/selected_cycles/selected_cycles.parquet"
REGISTRY = "universal_issue_state/v1/registries/universal_feature_registry_v1.json"
BASE = "universal_issue_state/v1/deterministic_features"


def config(experiment):
    value = read_json(inside(experiment, "config/features.json"))
    check_document(experiment, "t02_features", value)
    if digest(value) != "d0bc0d0e793e40e7a895f0bc91315c0db0fe92133ba5a75ff811c34156b6bace":
        raise ContractError("feature contract differs from the implemented README recipe; no silent reconfiguration")
    names = [f["name"] for f in value["features"]]
    expected = names + [n + "_missing" for n in names] + ["season_sin", "season_cos", "local_dst_flag"]
    if len(set(names)) != 34 or value["input_columns"] != expected or len(expected) != 71:
        raise ContractError("native feature order must be exactly 34 + 34 flags + 3 calendar columns")
    return value


def source_proof(project, cfg):
    """Registry and six footers only; no feature pages or truth outcomes."""
    import pyarrow as pa
    import pyarrow.parquet as pq
    registry = read_json(inside(project, REGISTRY))
    sources = {f["name"]: f for f in registry["features"]}
    proof = []
    for feature in cfg["features"]:
        source = sources.get(feature["source"])
        if source is None or source["unit"] != feature["source_unit"]:
            raise ContractError("source unit/identity mismatch: " + feature["source"])
        proof.append({**feature, "source_feature_id": source["feature_id"],
                      "source_operator": source["operator"], "source_window": source["window_id"],
                      "source_alignment": source["alignment_id"], "source_fields": source["source_fields"]})
    if registry["contracts"]["target_values_allowed"]:
        raise ContractError("source registry permits target values")
    required = {"issue_state_id", "target_date", "issue_time_utc", "wrfsfcf_cycle_init_utc",
                "wrfsubhf_cycle_init_utc", "feature_registry_id", "derivation_id"}
    required.update(f["source"] for f in cfg["features"])
    partitions = []
    for year in range(2021, 2027):
        rel = f"{BASE}/target_year={year}/part-{year}.parquet"
        file = pq.ParquetFile(inside(project, rel))
        if not required <= set(file.schema_arrow.names):
            raise ContractError("frozen source column missing: " + rel)
        for name in [f["source"] for f in cfg["features"]]:
            if file.schema_arrow.field(name).type not in [pa.float64(), pa.int32()]:
                raise ContractError("unexpected native source type: " + name)
        partitions.append({"path": rel, "rows": file.metadata.num_rows})
    if sum(p["rows"] for p in partitions) != 118536:
        raise ContractError("source issue count disagrees with accepted substrate")
    return {"registry_id": registry["registry_id"], "derivation_id": registry["derivation_id"],
            "features": proof, "partitions": partitions, "input_columns": cfg["input_columns"],
            "physical_ranges_not_repaired": True}


def stamp(value):
    value = datetime.fromisoformat(value.replace("Z", "+00:00")) if isinstance(value, str) else value
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ContractError("timezone-aware physical clock required")
    return value.astimezone(UTC)


def jsonable(value):
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, dict):
        return {k: jsonable(v) for k, v in value.items()}
    if isinstance(value, list):
        return [jsonable(v) for v in value]
    return value


def native_value(raw, transform, *, primary=False):
    if raw is None:
        return None
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        raise ContractError("non-numeric weather input")
    if not math.isfinite(raw):
        if primary:
            return None  # the primary anchor has an explicit nonfinite abstention policy
        raise ContractError("unexpected nonfinite ancillary weather input")
    if transform == "K_TO_F":
        result = (raw - 273.15) * 1.8 + 32
    elif transform == "DELTA_K_TO_F":
        result = raw * 1.8
    elif transform == "PERCENT_TO_FRACTION":
        result = raw / 100
    elif transform == "IDENTITY":
        result = float(raw)
    else:
        raise ContractError("undeclared transform")
    if not math.isfinite(result):
        raise ContractError("transformed value overflow")
    return result


def adapt(raw, spine, cycles, cfg, *, source_path, source_sha256):
    """Convert one verified frozen feature row; preserve provenance separately."""
    d, issue = parse_date(raw["target_date"]), stamp(raw["issue_time_utc"])
    local = issue.astimezone(DENVER)
    minute = local.hour * 60 + local.minute
    if (raw["issue_state_id"] != spine["issue_state_id"] or d != parse_date(spine["target_date"])
            or issue != stamp(spine["issue_time_utc"]) or local.date() != d
            or minute != spine["local_issue_hour"] * 60 + spine["local_issue_minute"]
            or not 120 <= minute <= 960 or minute % 15 or issue.second or issue.microsecond
            or bool(local.dst()) != bool(spine["local_dst_flag"]) or not spine["issue_state_eligible"]):
        raise ContractError("issue spine/feature clock mismatch")
    if set(cycles) != {"wrfsfcf", "wrfsubhf"}:
        raise ContractError("both product selection records are required")
    for product, cycle in cycles.items():
        if (cycle["issue_state_id"] != raw["issue_state_id"] or stamp(cycle["issue_time_utc"]) != issue
                or parse_date(cycle["target_date"]) != d
                or cycle["availability_policy_id"] != "KDEN_HIST_COMPLETE_L105_V1"):
            raise ContractError("cycle identity/availability policy mismatch")
        init = cycle["cycle_init_utc"]
        if init is None:
            if raw[f"{product}_cycle_init_utc"] is not None:
                raise ContractError("absent cycle has a feature initialization")
            continue
        init, available = stamp(init), stamp(cycle["emulated_complete_time_utc"])
        if (stamp(raw[f"{product}_cycle_init_utc"]) != init or available != init + timedelta(minutes=105)
                or available > issue or init.minute or init.second or init.microsecond):
            raise ContractError("feature references a wrong or unavailable cycle")
        for key, expected in [("cycle_age_minutes", (issue-init).total_seconds()/60),
                              ("availability_age_minutes", (issue-available).total_seconds()/60)]:
            if cycle[key] != expected:
                raise ContractError("selected cycle age inconsistent")
        previous = cycle.get("previous_cycle_init_utc")
        if previous is not None:
            if (stamp(previous) != init - timedelta(hours=1)
                    or stamp(cycle["previous_emulated_complete_time_utc"]) != stamp(previous)+timedelta(minutes=105)
                    or stamp(cycle["previous_emulated_complete_time_utc"]) > issue):
                raise ContractError("revision references an incompatible previous cycle")
    if raw["feature_registry_id"] != "KDEN_V375_UNIVERSAL_FEATURE_REGISTRY_V1" or raw["derivation_id"] != "KDEN_V375_DETERMINISTIC_FEATURES_V1":
        raise ContractError("frozen derivation identity mismatch")
    values = {}
    for feature in cfg["features"]:
        if feature["source"] not in raw:
            raise ContractError("absent source column is not an ancillary null")
        values[feature["name"]] = native_value(raw[feature["source"]], feature["transform"],
                                             primary=feature["name"] == cfg["primary_anchor"])
    for product, anchor_name in [("wrfsfcf", "anchor_h_f"), ("wrfsubhf", "anchor_q_f")]:
        if cycles[product]["cycle_init_utc"] is None and values[anchor_name] is not None:
            raise ContractError("weather value exists without a legal selected cycle")
    theta = 2 * math.pi * (d.timetuple().tm_yday - 1) / (366 if calendar.isleap(d.year) else 365)
    values.update({f["name"] + "_missing": float(values[f["name"]] is None) for f in cfg["features"]})
    values.update(season_sin=math.sin(theta), season_cos=math.cos(theta), local_dst_flag=float(bool(local.dst())))
    anchor = values[cfg["primary_anchor"]]
    return {"issue_state_id": raw["issue_state_id"], "target_date": d.isoformat(),
            "issue_time_utc": issue.isoformat(), "local_issue_minute": minute,
            "availability_policy_id": "KDEN_HIST_COMPLETE_L105_V1", "date_role": role(d),
            "native_status": "READY" if anchor is not None else "ABSTAIN_MISSING_OR_NONFINITE_Q05_ANCHOR",
            "source_feature_path": source_path, "source_feature_sha256": source_sha256,
            "source_provenance_json": json.dumps(jsonable({"spine": spine, "selected_cycles": cycles}), sort_keys=True, allow_nan=False),
            "coverage_diagnostics_json": json.dumps({k: v for k, v in raw.items() if "coverage_fraction" in k or "missing_count" in k}, sort_keys=True, allow_nan=False),
            **values}


def label_free_trend(query, history):
    """Same-minute previous 14 CALENDAR days, not last 14 rows or labels."""
    d, issue = parse_date(query["target_date"]), stamp(query["issue_time_utc"])
    minute = query["local_issue_minute"]
    values, ids, days = [], [], set()
    for row in history:
        hd = parse_date(row["target_date"])
        if row["local_issue_minute"] != minute or not d - timedelta(days=14) <= hd < d:
            raise ContractError("trend history is not exact-time previous-14-calendar-day support")
        if hd in days or stamp(row["issue_time_utc"]) >= issue:
            raise ContractError("duplicate/future trend history")
        days.add(hd)
        anchor = row["anchor_q_f"]
        if anchor is not None:
            if not math.isfinite(anchor):
                raise ContractError("nonfinite trend anchor")
            values.append(anchor)
            ids.append(row["issue_state_id"])
    current = query["anchor_q_f"]
    trend = current - math.fsum(values)/len(values) if current is not None and len(values) >= 7 else None
    return {"trend_q14_f": trend, "trend_q14_valid_days": len(values),
            "trend_q14_source_ids_json": json.dumps(ids),
            "trend_q14_status": "READY" if trend is not None else "INSUFFICIENT_HISTORY_OR_MISSING_CURRENT_ANCHOR"}


class FeatureContext:
    """Deterministic context-only imputation and uncorrected residual targets.

    A caller supplies ALL weather rows for the exact local minute. Label access
    is a separate object. It never requests query targets or holdout outcomes.
    There is no context-size option: all eligible earlier labelled days enter.
    """
    def __init__(self, weather_rows, truth_access, update_date, minute, cfg):
        self.cfg, self.minute = cfg, minute
        self.cutoff = label_cutoff(update_date)
        labels = {r["target_date"]: r["y_audited_f"] for r in truth_access.context(update_date)}
        rows, days, ids, exclusions = [], set(), set(), []
        for row in sorted(weather_rows, key=lambda r: r["target_date"]):
            if row["local_issue_minute"] != minute:
                raise ContractError("mixed issue-minute context")
            d = parse_date(row["target_date"])
            if d >= self.cutoff:
                continue  # unlabelled/query weather cannot fit any transformation
            if d in days or row["issue_state_id"] in ids:
                raise ContractError("duplicate weather day in exact-time context")
            days.add(d); ids.add(row["issue_state_id"])
            if row["target_date"] not in labels or row["anchor_q_f"] is None:
                exclusions.append({"target_date": str(d), "reason": "NO_AUTHORIZED_LABEL" if row["target_date"] not in labels else "MISSING_Q05_ANCHOR"})
                continue
            rows.append(row)
        if len(rows) < cfg["minimum_context_days"]:
            raise ContractError("insufficient context: fewer than 180 eligible distinct earlier days; no fallback")
        self.rows, self.medians, self.all_missing = rows, {}, []
        for f in cfg["features"]:
            key = f["name"]
            values = [r[key] for r in rows if r[key] is not None]
            if any(not math.isfinite(v) for v in values):
                raise ContractError("nonfinite context weather value")
            self.medians[key] = median(values) if values else 0.0
            if not values:
                self.all_missing.append(key)
        self.metadata = {"context_start": rows[0]["target_date"], "context_end": rows[-1]["target_date"],
                         "context_days": len(rows), "label_cutoff_exclusive": str(self.cutoff),
                         "local_issue_minute": minute, "medians": self.medians,
                         "all_missing_columns": self.all_missing, "input_columns": cfg["input_columns"],
                         "source_issue_state_ids": [r["issue_state_id"] for r in rows], "exclusions": exclusions}
        self.metadata["context_identity"] = digest(self.metadata)
        self.X = self.matrix(rows)
        import numpy as np
        self.y_residual_f = np.asarray([labels[r["target_date"]] - r["anchor_q_f"] for r in rows], dtype=np.float64)

    def matrix(self, rows):
        import numpy as np
        output, seen = [], set()
        for row in rows:
            if row["local_issue_minute"] != self.minute or row["availability_policy_id"] != "KDEN_HIST_COMPLETE_L105_V1":
                raise ContractError("query is incompatible with exact-time context")
            if row["target_date"] in seen:
                raise ContractError("duplicate query weather day")
            seen.add(row["target_date"])
            if row["anchor_q_f"] is None:
                raise ContractError("query abstains: Q05 primary anchor may not be imputed")
            values = [self.medians[f["name"]] if row[f["name"]] is None else row[f["name"]] for f in self.cfg["features"]]
            values += [float(row[f["name"]] is None) for f in self.cfg["features"]]
            values += [row[k] for k in ["season_sin", "season_cos", "local_dst_flag"]]
            if any(not math.isfinite(v) for v in values):
                raise ContractError("nonfinite model matrix")
            output.append(values)
        return np.asarray(output, dtype=np.float64).reshape(len(rows), 71)


class FeatureStore:
    """Model-facing accepted view, never an alternative truth loader.

    Verify the accepted adapter bytes once on opening. Context reads always
    include every earlier exact-minute weather state; labels decide eligibility
    through the separate chronology guard. Query columns never include y.
    """
    def __init__(self, experiment):
        import pyarrow.dataset as ds
        from .common import hash_file, verify_record
        self.cfg = config(experiment)
        release = verify_record(read_json(inside(experiment, "manifests/T02_PASS.json")))
        check_document(experiment, "t02_pass", release)
        for rel in ["config/features.json", "src/kden_r14_tabular/features.py"]:
            if hash_file(inside(experiment, rel)) != release["code_identity"][rel]:
                raise ContractError("feature contract changed after T02")
        paths = []
        for receipt in release["partitions"]:
            path = inside(experiment, receipt["path"])
            if hash_file(path) != receipt["sha256"]:
                raise ContractError("accepted model adapter bytes changed")
            paths.append(str(path))
        self.dataset = ds.dataset(paths, format="parquet")
        self.columns = ["issue_state_id", "target_date", "issue_time_utc", "local_issue_minute",
                        "availability_policy_id", "date_role", "native_status", "source_feature_path",
                        "source_feature_sha256", "trend_q14_f", "trend_q14_valid_days",
                        "trend_q14_source_ids_json", "trend_q14_status", *self.cfg["input_columns"]]

    def context(self, truth_access, update_date, minute):
        import pyarrow.dataset as ds
        cutoff = label_cutoff(update_date)
        rows = self.dataset.to_table(columns=self.columns, filter=(ds.field("local_issue_minute") == minute)
                                     & (ds.field("target_date") < str(cutoff))).to_pylist()
        return FeatureContext(rows, truth_access, update_date, minute, self.cfg)

    def queries(self, target_dates, minute):
        import pyarrow.dataset as ds
        dates = [str(parse_date(d)) for d in target_dates]
        if len(set(dates)) != len(dates): raise ContractError("duplicate query target date")
        rows = self.dataset.to_table(columns=self.columns, filter=(ds.field("local_issue_minute") == minute)
                                     & ds.field("target_date").isin(dates)).to_pylist()
        rows.sort(key=lambda r: r["target_date"])
        return {"rows": rows, "no_issue_state_dates": sorted(set(dates)-{r["target_date"] for r in rows}),
                "abstaining_issue_state_ids": [r["issue_state_id"] for r in rows if r["native_status"] != "READY"]}
