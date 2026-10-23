"""Full-selector GRIB inventory, decode, unit, and KDEN spatial contracts.

Inventory selection never relies on record number alone: parameter,
level/layer, cycle, valid time, step type, and interval boundaries must all
agree. ecCodes is loaded only when decoding is requested so planning and state
commands remain usable without the scientific runtime installed.
"""

from __future__ import annotations

import math
import re
import time
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any, Iterable, Mapping, Sequence

try:
    import eccodes
except ImportError:  # installed by the frozen acquisition environment
    eccodes = None  # type: ignore[assignment]


EARTH_RADIUS_SHAPE_6_M = 6_371_229.0
WEIGHT_TOLERANCE = 1e-10
KNOWN_GRID_IDS = {
    (1799, 1059): "HRRR_CONUS_NATIVE_LAMBERT_V4",
    (16, 31): "HRRR_CONUS_NATIVE_LAMBERT_V4_SYNTHETIC_CROP",
}


class GribContractError(RuntimeError):
    """A selector, message, unit, interval, or geometry contract failed."""


class SelectorResolutionError(GribContractError):
    """A frozen selector did not resolve exactly once."""


def _require_eccodes() -> Any:
    if eccodes is None:
        raise GribContractError(
            "ecCodes is required for GRIB decoding; install environment/requirements.lock"
        )
    return eccodes


@dataclass(frozen=True, slots=True)
class IndexRecord:
    record_number: int
    start_byte: int
    reference_token: str
    parameter: str
    level: str
    time_descriptor: str
    trailing_tokens: tuple[str, ...]
    original_line: str
    normalized_tokens: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class IntervalMetadata:
    semantics: str
    start_minute: int
    end_minute: int
    original_descriptor: str

    @property
    def duration_minutes(self) -> int:
        return self.end_minute - self.start_minute


@dataclass(frozen=True, slots=True)
class ResolvedIndexRange:
    record: IndexRecord
    end_byte: int
    match_count: int

    @property
    def size_bytes(self) -> int:
        return self.end_byte - self.record.start_byte + 1


@dataclass(frozen=True, slots=True)
class LambertGrid:
    grid_id: str
    nx: int
    ny: int
    latitude_first_deg: float
    longitude_first_deg: float
    lov_deg: float
    latin1_deg: float
    latin2_deg: float
    lad_deg: float
    dx_m: float
    dy_m: float
    earth_radius_m: float
    scanning_mode: int
    i_scans_negatively: bool
    j_scans_positively: bool
    j_points_are_consecutive: bool
    alternative_row_scanning: bool


@dataclass(frozen=True, slots=True)
class StationCoordinate:
    era_id: str
    latitude_deg: float
    longitude_deg: float


@dataclass(frozen=True, slots=True)
class DecodedMetadata:
    short_name: str
    name: str
    cf_name: str
    param_id: int
    discipline: int
    parameter_category: int
    parameter_number: int
    type_of_level: str
    level: float
    units: str
    cycle_time_utc: datetime
    valid_time_utc: datetime
    step_type: str
    step_range: str
    start_step_minutes: int
    end_step_minutes: int
    number_of_data_points: int
    number_of_values: int
    number_of_missing: int
    grid: LambertGrid


@dataclass(frozen=True, slots=True)
class SpatialExtraction:
    station_coordinate_era_id: str
    station_latitude_deg: float
    station_longitude_deg: float
    station_projected_x_m: float
    station_projected_y_m: float
    grid_fraction_i: float
    grid_fraction_j: float
    nearest_i: int
    nearest_j: int
    bilinear_nodes: tuple[tuple[int, int], ...]
    bilinear_weights: tuple[float, ...]
    operator_values: Mapping[str, float | None]
    tile_shape: tuple[int, int] | None
    tile_values: tuple[float | None, ...] | None
    tile_center_i: int | None
    tile_center_j: int | None

    def to_jsonable(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class DecodedExtraction:
    metadata: DecodedMetadata
    spatial: SpatialExtraction | None
    native_value_sample: float | None
    canonical_value_sample: float | None
    unit_roundtrip_error: float | None
    decode_seconds: float


def _norm(value: object) -> str:
    text = str(value).strip().lower().replace("×", "x")
    text = re.sub(r"\s+", " ", text)
    return text


def _compact(value: object) -> str:
    return re.sub(r"[^a-z0-9]+", "", _norm(value))


def parse_index(text: str) -> tuple[IndexRecord, ...]:
    records: list[IndexRecord] = []
    for raw in text.splitlines():
        if not raw.strip():
            continue
        pieces = raw.rstrip("\r\n").split(":")
        if len(pieces) < 6:
            raise SelectorResolutionError(f"malformed HRRR index line: {raw!r}")
        try:
            number = int(pieces[0])
            start = int(pieces[1])
        except ValueError as exc:
            raise SelectorResolutionError(f"non-numeric HRRR index prefix: {raw!r}") from exc
        records.append(
            IndexRecord(
                record_number=number,
                start_byte=start,
                reference_token=pieces[2].strip(),
                parameter=pieces[3].strip(),
                level=pieces[4].strip(),
                time_descriptor=pieces[5].strip(),
                trailing_tokens=tuple(token.strip() for token in pieces[6:] if token.strip()),
                original_line=raw,
                normalized_tokens=tuple(_norm(token) for token in pieces[2:] if token.strip()),
            )
        )
    if not records:
        raise SelectorResolutionError("HRRR index is empty")
    if any(right.start_byte <= left.start_byte for left, right in zip(records, records[1:])):
        raise SelectorResolutionError("HRRR index offsets are not strictly increasing")
    return tuple(records)


def _duration(value: str, unit: str) -> int:
    amount = int(value)
    return amount if unit.startswith("min") else 60 * amount


def parse_interval_descriptor(descriptor: str) -> IntervalMetadata:
    value = _norm(descriptor)
    if value in {"anl", "analysis"}:
        return IntervalMetadata("snapshot", 0, 0, descriptor)
    snapshot = re.fullmatch(r"(\d+)\s+(min|mins|minute|minutes|hour|hours)\s+fcst", value)
    if snapshot:
        end = _duration(snapshot.group(1), snapshot.group(2))
        return IntervalMetadata("snapshot", end, end, descriptor)
    interval = re.fullmatch(
        r"(\d+)-(\d+)\s+(min|mins|minute|minutes|hour|hours)\s+"
        r"(ave|avg|average|acc|accum|accumulation|max|maximum)\s+fcst",
        value,
    )
    if interval:
        start = _duration(interval.group(1), interval.group(3))
        end = _duration(interval.group(2), interval.group(3))
        kind = interval.group(4)
        semantics = {
            "ave": "preceding_average",
            "avg": "preceding_average",
            "average": "preceding_average",
            "acc": "preceding_accumulation",
            "accum": "preceding_accumulation",
            "accumulation": "preceding_accumulation",
            "max": "preceding_maximum",
            "maximum": "preceding_maximum",
        }[kind]
        if end < start:
            raise SelectorResolutionError(f"reversed interval descriptor: {descriptor!r}")
        return IntervalMetadata(semantics, start, end, descriptor)
    raise SelectorResolutionError(f"unsupported index interval descriptor: {descriptor!r}")


def _normalise_level(value: object) -> str:
    compact = _compact(value)
    aliases = {
        "surface": "surface",
        "meansealevel": "mean sea level",
        "700mb": "700 mb",
        "700hpa": "700 mb",
        "850mb": "850 mb",
        "850hpa": "850 mb",
        "2m": "2 m above ground",
        "2magl": "2 m above ground",
        "2maboveground": "2 m above ground",
        "10m": "10 m above ground",
        "10magl": "10 m above ground",
        "10maboveground": "10 m above ground",
        "0munderground": "0 m underground",
        "0mbelowground": "0 m underground",
        "boundarylayercloud": "boundary-layer cloud",
        "boundarylayercloudlayer": "boundary-layer cloud",
        "lowcloud": "low cloud",
        "lowcloudlayer": "low cloud",
        "entireatmosphere": "entire atmosphere",
        "entireatmosphereconsideredasasinglelayer": "entire atmosphere",
        "cloudceiling": "cloud ceiling",
    }
    return aliases.get(compact, _norm(value))


def record_matches_request(record: IndexRecord, request: Mapping[str, Any]) -> bool:
    cycle = _utc_datetime(request["cycle_init_utc"])
    if record.reference_token != f"d={cycle:%Y%m%d%H}":
        return False
    if _compact(record.parameter) != _compact(request["parameter"]):
        return False
    if _normalise_level(record.level) != _normalise_level(request["level"]):
        return False
    try:
        interval = parse_interval_descriptor(record.time_descriptor)
    except SelectorResolutionError:
        return False
    expected_semantics = str(request["interval_semantics"])
    if expected_semantics == "static_snapshot":
        expected_semantics = "snapshot"
    return (
        interval.semantics == expected_semantics
        and interval.end_minute == int(request["forecast_lead_min"])
        and interval.duration_minutes == int(request["interval_minutes"])
    )


def resolve_index_range(
    records: Sequence[IndexRecord],
    request: Mapping[str, Any],
    *,
    parent_size_bytes: int | None = None,
) -> ResolvedIndexRange:
    matches = [position for position, record in enumerate(records) if record_matches_request(record, request)]
    if len(matches) != 1:
        raise SelectorResolutionError(
            f"{request.get('field_registry_id')} expected one full-selector match; found {len(matches)}"
        )
    position = matches[0]
    record = records[position]
    if position + 1 < len(records):
        end = records[position + 1].start_byte - 1
    elif parent_size_bytes is not None:
        end = int(parent_size_bytes) - 1
    else:
        raise SelectorResolutionError("selected record is last and parent size is unavailable")
    if end < record.start_byte:
        raise SelectorResolutionError("resolved GRIB byte range is reversed")
    return ResolvedIndexRange(record, end, len(matches))


def _utc_datetime(value: object) -> datetime:
    if isinstance(value, datetime):
        result = value
    elif hasattr(value, "to_pydatetime"):
        result = value.to_pydatetime()
    else:
        result = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if result.tzinfo is None:
        raise GribContractError("timestamp must be timezone-aware")
    return result.astimezone(UTC)


def _message_datetime(date_value: object, time_value: object) -> datetime:
    text = f"{int(date_value):08d}{int(time_value):04d}"
    return datetime.strptime(text, "%Y%m%d%H%M").replace(tzinfo=UTC)


def _get(handle: Any, key: str, default: Any = None) -> Any:
    library = _require_eccodes()
    try:
        return library.codes_get(handle, key)
    except Exception:
        if default is not None:
            return default
        raise GribContractError(f"GRIB key is unavailable: {key}")


def _step_unit_minutes(value: object) -> int:
    compact = _compact(value)
    if compact in {"0", "m", "min", "minute", "minutes"}:
        return 1
    if compact in {"1", "h", "hr", "hour", "hours"}:
        return 60
    raise GribContractError(f"unsupported GRIB step unit: {value!r}")


def _step_value_minutes(value: object, step_unit: object) -> int:
    """Normalize numeric-hour and explicit-minute ecCodes step encodings."""

    if isinstance(value, (int, float)):
        return int(round(float(value) * _step_unit_minutes(step_unit)))
    text = str(value).strip().lower()
    match = re.fullmatch(r"([+-]?\d+(?:\.\d+)?)([a-z]+)?", text)
    if not match:
        raise GribContractError(f"unsupported GRIB step value: {value!r}")
    amount = float(match.group(1))
    suffix = match.group(2)
    if suffix is None:
        multiplier = _step_unit_minutes(step_unit)
    elif suffix in {"m", "min", "mins", "minute", "minutes"}:
        multiplier = 1
    elif suffix in {"h", "hr", "hrs", "hour", "hours"}:
        multiplier = 60
    else:
        raise GribContractError(f"unsupported GRIB step-value suffix: {value!r}")
    return int(round(amount * multiplier))


def _decode_grid(handle: Any) -> LambertGrid:
    if int(_get(handle, "edition")) != 2 or str(_get(handle, "gridType")) != "lambert":
        raise GribContractError("expected one GRIB2 Lambert-conformal message")
    if int(_get(handle, "shapeOfTheEarth")) != 6:
        raise GribContractError("only audited GRIB earth-shape code 6 is accepted")
    dimensions = (int(_get(handle, "Nx")), int(_get(handle, "Ny")))
    if dimensions not in KNOWN_GRID_IDS:
        raise GribContractError(f"unregistered Lambert grid dimensions: {dimensions}")
    grid = LambertGrid(
        grid_id=KNOWN_GRID_IDS[dimensions],
        nx=dimensions[0],
        ny=dimensions[1],
        latitude_first_deg=float(_get(handle, "latitudeOfFirstGridPointInDegrees")),
        longitude_first_deg=float(_get(handle, "longitudeOfFirstGridPointInDegrees")),
        lov_deg=float(_get(handle, "LoVInDegrees")),
        latin1_deg=float(_get(handle, "Latin1InDegrees")),
        latin2_deg=float(_get(handle, "Latin2InDegrees")),
        lad_deg=float(_get(handle, "LaDInDegrees")),
        dx_m=float(_get(handle, "DxInMetres")),
        dy_m=float(_get(handle, "DyInMetres")),
        earth_radius_m=EARTH_RADIUS_SHAPE_6_M,
        scanning_mode=int(_get(handle, "scanningMode")),
        i_scans_negatively=bool(int(_get(handle, "iScansNegatively"))),
        j_scans_positively=bool(int(_get(handle, "jScansPositively"))),
        j_points_are_consecutive=bool(int(_get(handle, "jPointsAreConsecutive"))),
        alternative_row_scanning=bool(int(_get(handle, "alternativeRowScanning"))),
    )
    if (
        grid.i_scans_negatively
        or not grid.j_scans_positively
        or grid.j_points_are_consecutive
        or grid.alternative_row_scanning
    ):
        raise GribContractError("unsupported scan geometry; +i/+j row-major HRRR is required")
    if grid.dx_m <= 0 or grid.dy_m <= 0:
        raise GribContractError("decoded grid spacing is not positive")
    return grid


def _validate_grid_point_counts(
    grid: LambertGrid,
    number_of_data_points: int,
    number_of_values: int,
    number_of_missing: int,
) -> None:
    """Validate complete and bitmap-backed GRIB grid cardinalities."""

    expected = grid.nx * grid.ny
    if number_of_data_points != expected:
        raise GribContractError("numberOfDataPoints disagrees with Nx times Ny")
    if min(number_of_values, number_of_missing) < 0:
        raise GribContractError("GRIB value/missing counts cannot be negative")
    if number_of_values + number_of_missing != number_of_data_points:
        raise GribContractError(
            "numberOfValues plus numberOfMissing disagrees with numberOfDataPoints"
        )


def _decode_metadata(handle: Any) -> DecodedMetadata:
    grid = _decode_grid(handle)
    data_points = int(_get(handle, "numberOfDataPoints"))
    values = int(_get(handle, "numberOfValues"))
    missing = int(_get(handle, "numberOfMissing"))
    _validate_grid_point_counts(grid, data_points, values, missing)
    step_units = _get(handle, "stepUnits")
    return DecodedMetadata(
        short_name=str(_get(handle, "shortName")),
        name=str(_get(handle, "name")),
        cf_name=str(_get(handle, "cfName", "unknown")),
        param_id=int(_get(handle, "paramId")),
        discipline=int(_get(handle, "discipline")),
        parameter_category=int(_get(handle, "parameterCategory")),
        parameter_number=int(_get(handle, "parameterNumber")),
        type_of_level=str(_get(handle, "typeOfLevel")),
        level=float(_get(handle, "level")),
        units=str(_get(handle, "units")),
        cycle_time_utc=_message_datetime(_get(handle, "dataDate"), _get(handle, "dataTime")),
        valid_time_utc=_message_datetime(_get(handle, "validityDate"), _get(handle, "validityTime")),
        step_type=str(_get(handle, "stepType")),
        step_range=str(_get(handle, "stepRange")),
        start_step_minutes=_step_value_minutes(_get(handle, "startStep"), step_units),
        end_step_minutes=_step_value_minutes(_get(handle, "endStep"), step_units),
        number_of_data_points=data_points,
        number_of_values=values,
        number_of_missing=missing,
        grid=grid,
    )


PARAMETER_ALIASES: Mapping[str, frozenset[str]] = {
    "HGT": frozenset({"gh", "z", "hgt", "geopotential", "geopotentialheight"}),
    "TMP": frozenset({"t", "2t", "skt", "tmp", "temperature", "airtemperature", "2metretemperature", "skintemperature"}),
    "DPT": frozenset({"dpt", "2d", "dewpoint", "dewpointtemperature", "2metredewpointtemperature"}),
    "UGRD": frozenset({
        "u", "10u", "ugrd", "avg10u", "ucomponentofwind",
        "timemean10metreuwindcomponent",
    }),
    "VGRD": frozenset({
        "v", "10v", "vgrd", "avg10v", "vcomponentofwind",
        "timemean10metrevwindcomponent",
    }),
    "GUST": frozenset({"gust", "windgust", "windgustatsurface"}),
    "MSLMA": frozenset({"mslma", "msl", "meansealevelpressure", "meansealevelpressureetareduction"}),
    "PRES": frozenset({"pres", "sp", "surfacepressure"}),
    "MSTAV": frozenset({"mstav", "soilw", "soilmoistureavailability"}),
    "SHTFL": frozenset({
        "shtfl", "sshf", "ishf", "surfacesensibleheatflux",
        "instantaneoussurfacesensibleheatnetflux",
    }),
    "LHTFL": frozenset({
        "lhtfl", "slhf", "slhtf", "surfacelatentheatflux",
        "surfacelatentheatnetflux",
    }),
    "GFLUX": frozenset({"gflux", "groundheatflux"}),
    "HPBL": frozenset({"hpbl", "blh", "planetaryboundarylayerheight"}),
    "WEASD": frozenset({"weasd", "sdwe", "waterequivalentofaccumulatedsnowdepth"}),
    "SNOWC": frozenset({"snowc", "snowcover"}),
    "SNOD": frozenset({"snod", "sde", "snowdepth"}),
    "TCDC": frozenset({"tcdc", "tcc", "totalcloudcover"}),
    "LCDC": frozenset({"lcdc", "lcc", "lowcloudcover"}),
    "DSWRF": frozenset({
        "dswrf", "ssrd", "sdswrf", "avgsdswrf",
        "downwardshortwaveradiationflux",
        "surfacedownwardshortwaveradiationflux",
        "timemeansurfacedownwardshortwaveradiationflux",
    }),
    "DLWRF": frozenset({
        "dlwrf", "strd", "sdlwrf", "downwardlongwaveradiationflux",
        "surfacedownwardlongwaveradiationflux",
    }),
    "USWRF": frozenset({
        "uswrf", "ssru", "suswrf", "upwardshortwaveradiationflux",
        "surfaceupwardshortwaveradiationflux",
    }),
    "ULWRF": frozenset({
        "ulwrf", "stru", "sulwrf", "upwardlongwaveradiationflux",
        "surfaceupwardlongwaveradiationflux",
    }),
    "CFNSF": frozenset({"cfnsf", "cloudforcingshortwaveflux"}),
    "REFC": frozenset({"refc", "compositereflectivity"}),
    "PRATE": frozenset({"prate", "precipitationrate"}),
    "APCP": frozenset({"apcp", "tp", "totalprecipitation"}),
    "PWAT": frozenset({"pwat", "tcwv", "precipitablewater"}),
    "VIS": frozenset({"vis", "visibility"}),
    "AOTK": frozenset({"aotk", "aerosolopticalthickness"}),
    "CAPE": frozenset({"cape", "convectiveavailablepotentialenergy"}),
    "CIN": frozenset({"cin", "convectiveinhibition"}),
}

# ecCodes 2.45 does not name this NCEP local-table parameter, so its audited
# GRIB2 discipline/category/number is the only decoded parameter identity.
PARAMETER_CODE_ALIASES: Mapping[str, frozenset[tuple[int, int, int]]] = {
    "AOTK": frozenset({(0, 20, 102)}),
}


LEVEL_TYPES: Mapping[str, frozenset[tuple[str, int]]] = {
    "700 mb": frozenset({("isobaricinhpa", 700)}),
    "850 mb": frozenset({("isobaricinhpa", 850)}),
    "surface": frozenset({("surface", 0), ("heightaboveground", 0)}),
    "mean sea level": frozenset({("meansea", 0)}),
    "2 m above ground": frozenset({("heightaboveground", 2)}),
    "10 m above ground": frozenset({("heightaboveground", 10)}),
    "0 m underground": frozenset({("depthbelowland", 0), ("depthbelowlandlayer", 0)}),
    "boundary-layer cloud": frozenset({("atmospheresinglelayer", 0), ("boundarylayercloudlayer", 0)}),
    "low cloud": frozenset({("lowcloudlayer", 0), ("lowcloud", 0)}),
    "entire atmosphere": frozenset({
        ("entireatmosphere", 0), ("atmospheresinglelayer", 0), ("atmosphere", 0),
    }),
    "cloud ceiling": frozenset({("cloudceiling", 0)}),
}


def _parameter_matches(parameter: str, metadata: DecodedMetadata) -> bool:
    observed = {_compact(metadata.short_name), _compact(metadata.name), _compact(metadata.cf_name)}
    normalized = str(parameter).upper()
    allowed = PARAMETER_ALIASES.get(normalized)
    if allowed is not None and bool(observed & allowed):
        return True
    observed_code = (
        int(metadata.discipline),
        int(metadata.parameter_category),
        int(metadata.parameter_number),
    )
    return observed_code in PARAMETER_CODE_ALIASES.get(normalized, frozenset())


def _level_matches(level: str, metadata: DecodedMetadata) -> bool:
    normalized = _normalise_level(level)
    expected = LEVEL_TYPES.get(normalized)
    if expected is None:
        return False
    observed = (_compact(metadata.type_of_level), int(round(metadata.level)))
    return observed in expected


def validate_decoded_identity(
    metadata: DecodedMetadata,
    request: Mapping[str, Any],
    record: IndexRecord,
) -> None:
    if not record_matches_request(record, request):
        raise GribContractError("selected index record no longer matches the request")
    if metadata.cycle_time_utc != _utc_datetime(request["cycle_init_utc"]):
        raise GribContractError("decoded cycle time disagrees with request")
    if metadata.valid_time_utc != _utc_datetime(request["valid_time_utc"]):
        raise GribContractError("decoded valid time disagrees with request")
    if not _parameter_matches(str(request["parameter"]), metadata):
        raise GribContractError(
            f"decoded parameter disagrees with {request['parameter']}: {metadata.short_name}/{metadata.name}"
        )
    if not _level_matches(str(request["level"]), metadata):
        raise GribContractError(
            f"decoded level disagrees with {request['level']}: {metadata.type_of_level}/{metadata.level}"
        )
    expected_semantics = str(request["interval_semantics"])
    if expected_semantics == "static_snapshot":
        expected_semantics = "snapshot"
    decoded_semantics = {
        "instant": "snapshot",
        "avg": "preceding_average",
        "accum": "preceding_accumulation",
        "max": "preceding_maximum",
    }.get(_norm(metadata.step_type))
    if decoded_semantics != expected_semantics:
        raise GribContractError(
            f"decoded stepType {metadata.step_type!r} disagrees with {expected_semantics!r}"
        )
    expected_end = int(request["forecast_lead_min"])
    expected_start = expected_end - int(request["interval_minutes"])
    if (metadata.start_step_minutes, metadata.end_step_minutes) != (expected_start, expected_end):
        raise GribContractError(
            "decoded step interval disagrees with frozen preceding-interval boundaries"
        )


UNIT_ALIASES: Mapping[str, frozenset[str]] = {
    "1": frozenset({"1", "numeric"}),
    "%": frozenset({"%", "percent"}),
    "K": frozenset({"k", "kelvin"}),
    "Pa": frozenset({"pa", "pascal", "pascals"}),
    "gpm": frozenset({"gpm", "gp m", "geopotential metre", "geopotential metres"}),
    "m": frozenset({"m", "metre", "metres"}),
    "m s-1": frozenset({"m s-1", "m s**-1", "m/s", "ms-1"}),
    "W m-2": frozenset({"w m-2", "w m**-2", "w/m2"}),
    "kg m-2": frozenset({"kg m-2", "kg m**-2", "kg/m2"}),
    "kg m-2 s-1": frozenset({"kg m-2 s-1", "kg m**-2 s**-1", "kg/m2/s"}),
    # ecCodes exposes operational HRRR composite reflectivity as ``dB`` even
    # though the frozen scientific registry uses the meteorological label dBZ.
    "dBZ": frozenset({"dbz", "db"}),
    "J kg-1": frozenset({"j kg-1", "j kg**-1", "j/kg"}),
}


def canonical_unit_name(value: object) -> str:
    normalized = _norm(value)
    for canonical, aliases in UNIT_ALIASES.items():
        if normalized in {_norm(alias) for alias in aliases}:
            return canonical
    raise GribContractError(f"unsupported native unit: {value!r}")


def convert_native_to_canonical(value: float, native_unit: str, canonical_unit: str) -> float:
    native = canonical_unit_name(native_unit)
    target = canonical_unit_name(canonical_unit)
    if native == target:
        return float(value)
    if {native, target} == {"gpm", "m"}:
        return float(value)
    raise GribContractError(f"unsupported unit conversion: {native_unit!r} -> {canonical_unit!r}")


def convert_canonical_to_native(value: float, canonical_unit: str, native_unit: str) -> float:
    return convert_native_to_canonical(value, canonical_unit, native_unit)


def decoded_unit_matches_registry(
    parameter: str, decoded_unit: str, registry_native_unit: str
) -> bool:
    """Accept only audited provider/decoder spellings of a frozen native unit."""

    registered = canonical_unit_name(registry_native_unit)
    if (
        str(parameter).upper() == "AOTK"
        and _compact(decoded_unit) == "unknown"
        and registered == "1"
    ):
        return True
    decoded = canonical_unit_name(decoded_unit)
    if decoded == registered:
        return True
    return str(parameter).upper() == "HGT" and {decoded, registered} == {"gpm", "m"}


def _projection_constants(grid: LambertGrid) -> tuple[float, float, float]:
    phi1 = math.radians(grid.latin1_deg)
    phi2 = math.radians(grid.latin2_deg)
    if math.isclose(phi1, phi2, abs_tol=1e-14):
        n = math.sin(phi1)
    else:
        n = math.log(math.cos(phi1) / math.cos(phi2)) / math.log(
            math.tan(math.pi / 4 + phi2 / 2) / math.tan(math.pi / 4 + phi1 / 2)
        )
    if not math.isfinite(n) or math.isclose(n, 0.0, abs_tol=1e-15):
        raise GribContractError("degenerate Lambert cone constant")
    factor = math.cos(phi1) * math.tan(math.pi / 4 + phi1 / 2) ** n / n
    lov = math.radians((grid.lov_deg + 180.0) % 360.0 - 180.0)
    return n, factor, lov


def project_absolute(grid: LambertGrid, latitude_deg: float, longitude_deg: float) -> tuple[float, float]:
    n, factor, lov = _projection_constants(grid)
    phi = math.radians(latitude_deg)
    lon = math.radians((longitude_deg + 180.0) % 360.0 - 180.0)
    delta = (lon - lov + math.pi) % (2 * math.pi) - math.pi
    rho = grid.earth_radius_m * factor / math.tan(math.pi / 4 + phi / 2) ** n
    theta = n * delta
    return rho * math.sin(theta), -rho * math.cos(theta)


def grid_fraction(grid: LambertGrid, latitude_deg: float, longitude_deg: float) -> tuple[float, float]:
    first_x, first_y = project_absolute(grid, grid.latitude_first_deg, grid.longitude_first_deg)
    station_x, station_y = project_absolute(grid, latitude_deg, longitude_deg)
    return (station_x - first_x) / grid.dx_m, (station_y - first_y) / grid.dy_m


def _cell(value: float, upper: int) -> tuple[int, int, float]:
    if value < 0 or value > upper:
        raise GribContractError("station lies outside decoded grid")
    if math.isclose(value, upper, abs_tol=1e-12):
        return upper - 1, upper, 1.0
    lower = math.floor(value)
    return lower, lower + 1, value - lower


def bilinear_indices_and_weights(
    fraction_i: float, fraction_j: float, nx: int, ny: int
) -> tuple[tuple[tuple[int, int], ...], tuple[float, ...]]:
    i0, i1, u = _cell(fraction_i, nx - 1)
    j0, j1, v = _cell(fraction_j, ny - 1)
    indices = ((i0, j0), (i1, j0), (i0, j1), (i1, j1))
    weights = ((1 - u) * (1 - v), u * (1 - v), (1 - u) * v, u * v)
    if not all(math.isfinite(weight) and weight >= 0 for weight in weights):
        raise GribContractError("bilinear weights are not finite/nonnegative")
    if abs(sum(weights) - 1.0) > WEIGHT_TOLERANCE:
        raise GribContractError("bilinear weights do not sum to one")
    return indices, weights


def _tile_indices(center_i: int, center_j: int, size: int, grid: LambertGrid) -> tuple[tuple[int, int], ...]:
    if size not in {3, 9}:
        raise GribContractError(f"unsupported tile size: {size}")
    radius = size // 2
    if not (
        radius <= center_i < grid.nx - radius
        and radius <= center_j < grid.ny - radius
    ):
        raise GribContractError(f"{size}x{size} tile crosses the grid boundary")
    return tuple(
        (i, j)
        for j in range(center_j - radius, center_j + radius + 1)
        for i in range(center_i - radius, center_i + radius + 1)
    )


def _read_node_values(
    handle: Any,
    indices: Sequence[tuple[int, int]],
    grid: LambertGrid,
) -> dict[tuple[int, int], float | None]:
    unique = tuple(dict.fromkeys(indices))
    linear = [j * grid.nx + i for i, j in unique]
    values = _require_eccodes().codes_get_elements(handle, "values", linear)
    bitmap_present = bool(int(_get(handle, "bitmapPresent", 0)))
    missing_value = float(_get(handle, "missingValue")) if bitmap_present else None
    result: dict[tuple[int, int], float | None] = {}
    for index, raw in zip(unique, values, strict=True):
        value = float(raw)
        if bitmap_present and (
            not math.isfinite(value) or value == missing_value
        ):
            result[index] = None
        elif not math.isfinite(value):
            raise GribContractError(f"required local node is missing/nonfinite: {index}")
        else:
            result[index] = value
    return result


def _extract_spatial(
    handle: Any,
    grid: LambertGrid,
    station: StationCoordinate,
    operators: Iterable[str],
) -> SpatialExtraction | None:
    normalized = tuple(dict.fromkeys(str(value) for value in operators))
    if normalized == ("grid lineage",) or not normalized:
        return None
    allowed = {"BI", "NN", "3x3", "9x9"}
    if not set(normalized).issubset(allowed):
        raise GribContractError(f"unknown spatial operators: {sorted(set(normalized) - allowed)}")
    fraction_i, fraction_j = grid_fraction(grid, station.latitude_deg, station.longitude_deg)
    nearest = (math.floor(fraction_i + 0.5), math.floor(fraction_j + 0.5))
    bilinear, weights = bilinear_indices_and_weights(fraction_i, fraction_j, grid.nx, grid.ny)
    needed: list[tuple[int, int]] = []
    if "BI" in normalized:
        needed.extend(bilinear)
    if "NN" in normalized:
        needed.append(nearest)
    # When both sizes are requested the canonical archive stores only 9x9;
    # the centered 3x3 is derived later without another decode or download.
    tile_size = 9 if "9x9" in normalized else (3 if "3x3" in normalized else None)
    tile_indices: tuple[tuple[int, int], ...] = ()
    if tile_size is not None:
        tile_indices = _tile_indices(nearest[0], nearest[1], tile_size, grid)
        needed.extend(tile_indices)
    values = _read_node_values(handle, needed, grid)
    operator_values: dict[str, float | None] = {}
    if "BI" in normalized:
        bilinear_values = [values[index] for index in bilinear]
        operator_values["BI"] = (
            None
            if any(value is None for value in bilinear_values)
            else sum(
                float(value) * weight
                for value, weight in zip(bilinear_values, weights, strict=True)
            )
        )
    if "NN" in normalized:
        operator_values["NN"] = values[nearest]
    return SpatialExtraction(
        station_coordinate_era_id=station.era_id,
        station_latitude_deg=station.latitude_deg,
        station_longitude_deg=station.longitude_deg,
        station_projected_x_m=fraction_i * grid.dx_m,
        station_projected_y_m=fraction_j * grid.dy_m,
        grid_fraction_i=fraction_i,
        grid_fraction_j=fraction_j,
        nearest_i=nearest[0],
        nearest_j=nearest[1],
        bilinear_nodes=bilinear,
        bilinear_weights=weights,
        operator_values=operator_values,
        tile_shape=None if tile_size is None else (tile_size, tile_size),
        tile_values=None if tile_size is None else tuple(values[index] for index in tile_indices),
        tile_center_i=None if tile_size is None else tile_size // 2,
        tile_center_j=None if tile_size is None else tile_size // 2,
    )


def extract_registered_supports(
    handle: Any,
    grid: LambertGrid,
    supports: Sequence[Mapping[str, Any]],
    *,
    interpolation: str,
    fraction_tolerance: float = 1e-8,
    weight_tolerance: float = 1e-10,
) -> tuple[tuple[float | None, ...], int]:
    """Extract a positionally bound set of pre-registered spatial supports.

    The registered latitude/longitude is projected again against the decoded
    GRIB grid.  Frozen nodes and weights must agree before any value is used;
    this prevents a geometry artifact for another grid from being applied
    silently.  Missing nodes clear the corresponding coverage bit.
    """

    if interpolation not in {"BILINEAR", "NEAREST"}:
        raise GribContractError(f"unsupported registered-support interpolation: {interpolation}")
    ordered = sorted(supports, key=lambda row: int(row["support_index"]))
    if [int(row["support_index"]) for row in ordered] != list(range(len(ordered))):
        raise GribContractError("registered support indices are not contiguous")
    resolved: list[tuple[tuple[tuple[int, int], ...], tuple[float, ...]]] = []
    needed: list[tuple[int, int]] = []
    for support in ordered:
        fraction_i, fraction_j = grid_fraction(
            grid,
            float(support["target_latitude_deg"]),
            float(support["target_longitude_deg"]),
        )
        if (
            abs(fraction_i - float(support["grid_fraction_i"])) > fraction_tolerance
            or abs(fraction_j - float(support["grid_fraction_j"])) > fraction_tolerance
        ):
            raise GribContractError(
                f"decoded grid disagrees with registered support {support['support_id']}"
            )
        if interpolation == "NEAREST":
            observed = (math.floor(fraction_i + 0.5), math.floor(fraction_j + 0.5))
            frozen = support["nearest_node"]
            expected = (int(frozen["i"]), int(frozen["j"]))
            if observed != expected:
                raise GribContractError(
                    f"nearest node changed for registered support {support['support_id']}"
                )
            nodes = (expected,)
            weights = (1.0,)
        else:
            nodes, weights = bilinear_indices_and_weights(
                fraction_i, fraction_j, grid.nx, grid.ny
            )
            frozen_nodes = tuple(
                (int(node["i"]), int(node["j"])) for node in support["bilinear_nodes"]
            )
            frozen_weights = tuple(float(node["weight"]) for node in support["bilinear_nodes"])
            if nodes != frozen_nodes or any(
                abs(left - right) > weight_tolerance
                for left, right in zip(weights, frozen_weights, strict=True)
            ):
                raise GribContractError(
                    f"bilinear geometry changed for registered support {support['support_id']}"
                )
        resolved.append((nodes, weights))
        needed.extend(nodes)

    node_values = _read_node_values(handle, needed, grid)
    values: list[float | None] = []
    coverage_mask = 0
    for index, (nodes, weights) in enumerate(resolved):
        samples = [node_values[node] for node in nodes]
        if any(value is None for value in samples):
            values.append(None)
            continue
        value = sum(
            float(sample) * weight
            for sample, weight in zip(samples, weights, strict=True)
        )
        if not math.isfinite(value):
            raise GribContractError("registered support produced a nonfinite value")
        values.append(value)
        coverage_mask |= 1 << index
    return tuple(values), coverage_mask


def decode_and_extract(
    payload: bytes,
    *,
    request: Mapping[str, Any],
    index_record: IndexRecord,
    station: StationCoordinate,
    operators: Sequence[str],
    native_unit: str,
    canonical_unit: str,
) -> DecodedExtraction:
    """Decode one verified message, validate its identity, and extract KDEN nodes."""

    if not (payload.startswith(b"GRIB") and payload.endswith(b"7777")):
        raise GribContractError("payload is not one framed GRIB message")
    started = time.monotonic()
    library = _require_eccodes()
    handle = library.codes_new_from_message(payload)
    if handle is None:
        raise GribContractError("ecCodes could not create a message handle")
    try:
        encoded = bytes(library.codes_get_message(handle))
        if len(encoded) != len(payload):
            raise GribContractError("bounded payload contains trailing or multiple message bytes")
        metadata = _decode_metadata(handle)
        validate_decoded_identity(metadata, request, index_record)
        if not decoded_unit_matches_registry(
            str(request["parameter"]), metadata.units, native_unit
        ):
            raise GribContractError(
                f"decoded unit {metadata.units!r} disagrees with registry native unit {native_unit!r}"
            )
        spatial = _extract_spatial(handle, metadata.grid, station, operators)
        sample = None
        if spatial is not None:
            sample = next(
                (value for value in spatial.operator_values.values() if value is not None),
                None,
            )
            if sample is None:
                sample = next(
                    (
                        float(value)
                        for value in (spatial.tile_values or ())
                        if value is not None
                    ),
                    None,
                )
        canonical = None if sample is None else convert_native_to_canonical(sample, native_unit, canonical_unit)
        reconstructed = None if canonical is None else convert_canonical_to_native(canonical, canonical_unit, native_unit)
        error = None if sample is None else abs(reconstructed - sample)
        if error is not None and error > 1e-9 * max(1.0, abs(sample)):
            raise GribContractError("unit conversion failed round-trip tolerance")
        return DecodedExtraction(
            metadata=metadata,
            spatial=spatial,
            native_value_sample=sample,
            canonical_value_sample=canonical,
            unit_roundtrip_error=error,
            decode_seconds=time.monotonic() - started,
        )
    finally:
        library.codes_release(handle)
