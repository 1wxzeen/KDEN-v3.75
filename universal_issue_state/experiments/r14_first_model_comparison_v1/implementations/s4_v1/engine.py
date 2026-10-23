"""Nested tuning and immutable forecasts. No outer-outcome accessor exists here."""
from pathlib import Path
from datetime import date, timedelta
import fcntl, json, os, platform, shutil, signal, tempfile, time
import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
import scipy
import s0
from r14_s1.data import read_dates, unique_rows, as_date
from r14_s1.forecast import publish_partition
from r14_s2.model import support_summary, day_losses
from r14_s3 import runtime
from r14_s3.data import Loader, weather, center
from r14_s3.anen import doy, scale_fit

MODELS = runtime.MODELS
BASELINE = 'r14-s2-20260925T185129Z'
TIES = {'ANEN': ('seasonal_half_width_days', 'neighbors', 'bandwidth_multiplier', 'kernel_sigma_f')}
digest = runtime.digest


def write(path, value):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + '.tmp')
    runtime.save(temp, value); os.replace(temp, path)


def seal(path, value):
    value = dict(value); value['record_sha256'] = digest(value)
    write(path, value); return value


def freeze(path, value):
    if path.exists():
        s0.require(s0.read_json(path) == value, 'Frozen artifact changed: ' + str(path))
    else:
        write(path, value)
    return value


def binding(root, experiment, project):
    s3 = experiment / 'implementations/s3_v1'
    runtime.validate(s3, experiment, project)
    release = s0.read_json(root / 'RELEASE.json'); s0.check_record(release)
    for rel, h in release['files'].items():
        s0.require(s0.sha256(s0.safe_path(root, rel)) == h, 'S4 implementation changed: ' + rel)
    config = s0.read_json(root / 'config.json')
    for rel, h in config['parents'].items():
        s0.require(s0.sha256(s0.safe_path(experiment, rel)) == h, 'S4 parent changed: ' + rel)
    s0.require(os.environ.get('OPENBLAS_NUM_THREADS') == '1' and os.environ.get('OMP_NUM_THREADS') == '1', 'Use the single-threaded S4 launcher')
    return {'schema': 'R14_S4_RUN_V1', 's4_release_sha256': s0.sha256(root / 'RELEASE.json'),
            'parents': config['parents'], 'environment': {'python': platform.python_version(),
            'numpy': np.__version__, 'scipy': scipy.__version__, 'pyarrow': pa.__version__,
            'platform': platform.platform(), 'OPENBLAS_NUM_THREADS': '1', 'OMP_NUM_THREADS': '1'}}


def common_support(train, query, candidates, config):
    """Feature-only intersection, independent of temperatures and solver outcomes."""
    mask = query.available.copy()
    if not train.available.any():
        return np.zeros_like(mask)
    if query.model_id != 'ANEN':
        return mask
    width = min(c['parameters']['seasonal_half_width_days'] for c in candidates)
    required = max(40, max(c['parameters']['neighbors'] for c in candidates))
    X = weather(train, config); groups = {}
    for minute in {m['local_minutes_since_0200'] for m in train.metadata}:
        ids = [i for i, m in enumerate(train.metadata) if train.available[i] and m['local_minutes_since_0200'] == minute]
        if ids and scale_fit(X[ids])[2].any():
            groups[minute] = np.array([doy(train.metadata[i]['target_date']) for i in ids])
    for i, m in enumerate(query.metadata):
        days = groups.get(m['local_minutes_since_0200'], np.array([]))
        delta = np.abs(days - doy(m['target_date']))
        mask[i] &= int(np.sum(np.minimum(delta, 366-delta) <= width)) >= required
    return mask


def choose(candidates, losses, invalid):
    valid = [c for c in candidates if c['candidate_id'] not in invalid]
    s0.require(set(losses) == {c['candidate_id'] for c in candidates}, 'Incomplete candidate score registry')
    if not valid:
        return None, {}
    sets = [set(losses[c['candidate_id']]) for c in valid]
    s0.require(sets[0] and all(s == sets[0] for s in sets), 'Candidate scoring populations differ')
    means = {c['candidate_id']: float(np.mean(list(losses[c['candidate_id']].values()))) for c in valid}
    s0.require(all(np.isfinite(list(means.values()))), 'Nonfinite selection score')
    tied = [c for c in valid if means[c['candidate_id']] <= min(means.values()) + 1e-10]
    order = TIES.get(valid[0]['model_id'], ('lambda_mu', 'lambda_scale'))
    return max(tied, key=lambda c: tuple(c['parameters'][k] for k in order)), means


def verify_unit(path, run_sha, candidate=None, ids=None):
    record = s0.read_json(path / 'UNIT.json'); s0.check_record(record)
    s0.require(record['run_binding_sha256'] == run_sha, 'Checkpoint belongs to another run')
    if candidate is not None:
        s0.require(record['candidate'] == candidate, 'Checkpoint candidate changed')
    if ids is not None:
        s0.require(record['expected_issue_ids_sha256'] == digest(ids), 'Checkpoint population changed')
    for rel, h in record['files'].items():
        s0.require(s0.sha256(s0.safe_path(path, rel)) == h, 'Checkpoint bytes changed: ' + str(path / rel))
    if record['status'] == 'PREDICTIONS_FROZEN':
        m = s0.read_json(path / 'forecast/manifest.json'); s0.check_record(m)
        s0.require(m['rows'] == record['rows'], 'Checkpoint row count changed')
    else:
        s0.require(record['status'] == 'INVALID_SOLVER', 'Unknown checkpoint state')
    return record


def diagnostic_json(value):
    """Keep failed optimizer diagnostics serializable without discarding nonfinite evidence."""
    if isinstance(value, dict): return {k: diagnostic_json(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)): return [diagnostic_json(v) for v in value]
    if isinstance(value, (float, np.floating)):
        return float(value) if np.isfinite(value) else ('NaN' if np.isnan(value) else 'Infinity' if value > 0 else '-Infinity')
    if isinstance(value, np.integer): return int(value)
    return value


def make_unit(path, train, query, y, candidate, config, s3, loader, run_sha, cutoff,
              shared_fit=None, unsupported=None, artifact_template=None):
    ids = [m['issue_state_id'] for m in query.metadata]
    if path.exists():
        return verify_unit(path, run_sha, candidate, ids)
    path.parent.mkdir(parents=True, exist_ok=True)
    scratch = Path(tempfile.mkdtemp(prefix='.uncommitted-', dir=path.parent)); started = time.monotonic()
    record = {'run_binding_sha256': run_sha, 'candidate': candidate, 'outer': query.outer_fold_id,
              'inner': query.inner_fold_id, 'rows': len(ids), 'expected_issue_ids_sha256': digest(ids),
              'assessment_outcomes_used': False}
    try:
        params = candidate['parameters'] if candidate else {}
        ident = runtime.identity(s3, loader, query.model_id, params)
        ident['s4_run_binding_sha256'] = run_sha
        fitted = shared_fit; failure = unsupported
        if not failure and fitted is None:
            try:
                fitted = runtime.fit(train, y, config, params)
            except s0.ContractError as exc:
                # Only the preregistered scientific solver failure is terminal.
                # I/O, programming, and integrity errors stop the run and may be resumed.
                if str(exc) != 'ALL_GAM_STARTS_FAILED':
                    raise
                failure = 'ALL_GAM_STARTS_FAILED'
                runtime.save(scratch / 'solver_failure.json', {'reason': failure, 'starts': diagnostic_json(exc.starts)})
        if failure and query.inner_fold_id is not None:
            record.update(status='INVALID_SOLVER', reason=failure)
        else:
            if failure:
                runtime.save(scratch / 'identity.json', ident)
                def abstentions():
                    centers = center(query)
                    for i, m in enumerate(query.metadata):
                        row = {k: m[k] for k in ['issue_state_id', 'target_date', 'statistical_group_id', 'issue_time_utc', 'local_minutes_since_0200', 'issue_count_for_target_day']}
                        row.update(model_id=query.model_id, outer_fold_id=query.outer_fold_id, inner_fold_id=None,
                                   status='ABSTAIN', abstention_reason=failure, probabilities=None, point_f=None,
                                   baseline_center_f=float(centers[i]) if np.isfinite(centers[i]) else None,
                                   training_start=min(train.dates), training_end=max(train.dates), label_cutoff=cutoff,
                                   configuration_sha256=ident['configuration_sha256'], code_sha256=ident['code_sha256'],
                                   input_hashes_json=json.dumps(ident['input_hashes'], sort_keys=True),
                                   diagnostics_json=json.dumps({'unsupported_model': True, 'reason': failure}))
                        yield row
                rows = abstentions()
            else:
                if query.model_id == 'ANEN' and artifact_template is not None:
                    # Analog training state is independent of k/window/bandwidth/sigma.
                    # Hard links share immutable bytes while each unit remains reloadable.
                    for name in ['training.npz', 'training_metadata.json', 'fit_state.json']:
                        os.link(artifact_template / name, scratch / name)
                    runtime.save(scratch / 'identity.json', ident)
                else:
                    if hasattr(fitted, 'starts'): fitted.starts = diagnostic_json(fitted.starts)
                    runtime.fit_artifact(scratch, fitted, y, ident)
                rows = runtime.records(fitted, query, params, ident, cutoff)
            publish_partition(scratch / 'forecast', rows, ids)
            record.update(status='PREDICTIONS_FROZEN', unsupported_reason=failure)
        record.update(seconds=time.monotonic()-started,
                      files={p.relative_to(scratch).as_posix(): s0.sha256(p) for p in scratch.rglob('*') if p.is_file()})
        result = seal(scratch / 'UNIT.json', record)
        os.rename(scratch, path)
        return result
    finally:
        if scratch.exists(): shutil.rmtree(scratch)


def aligned_rows(path, expected_ids, columns):
    rows = pq.read_table(path / 'forecast/predictions.parquet', columns=['issue_state_id'] + columns).to_pylist()
    lookup = {r['issue_state_id']: r for r in rows}
    s0.require(len(rows) == len(lookup) == len(expected_ids) and set(lookup) == set(expected_ids), 'Forecast key mismatch')
    return [lookup[key] for key in expected_ids]


def inner_labels(loader, query, mask, paths, candidates, run_sha):
    """No labels until the entire registered candidate set has a sealed disposition."""
    s0.require(query.split == 'ASSESS' and query.inner_fold_id is not None, 'Outer scoring forbidden in S4')
    s0.require(len(paths) == len(candidates) and len({str(p) for p in paths}) == len(candidates), 'Unsealed candidate set')
    registered = runtime.candidates(loader.experiment / 'implementations/s3_v1', query.model_id)
    s0.require(candidates == registered, 'Inner accessor requires the complete registered candidate family')
    ids = [m['issue_state_id'] for m in query.metadata]
    for path, candidate in zip(paths, candidates):
        unit = verify_unit(path, run_sha, candidate, ids)
        s0.require(unit['inner'] == query.inner_fold_id and unit['outer'] == query.outer_fold_id, 'Inner fold mismatch')
    dates = sorted({d for d, ok in zip(query.dates, mask) if ok})
    s0.require(dates and set(dates) <= set(loader.fold_dates(query.outer_fold_id, 'ASSESS', query.inner_fold_id)), 'Unauthorized inner dates')
    t = loader.supplement['truth_accessor']
    catalog = read_dates(loader._input(t['catalog']), t['catalog_authorization_columns'], dates).to_pylist()
    authorized = unique_rows(catalog, ['target_date'])
    s0.require(set(authorized) == {(d,) for d in dates}, 'Truth authorization missing')
    for r in catalog:
        s0.require(r['truth_group'] == 'development' and r['label_available_for_supervised_use'] is True and r['source_artifact_path'] == t['source_path'] and r['source_artifact_sha256'] == t['source_sha256'], 'Unauthorized inner truth')
    source = loader._input(t['source_path'])
    source_dates = pq.ParquetFile(source).read(columns=['target_date'])['target_date'].to_pylist()
    s0.require(max(source_dates) <= as_date(t['source_max_date']), 'Source contains reserved/tail dates')
    values = unique_rows(read_dates(source, ['target_date', 'y_audited_f'], dates).to_pylist(), ['target_date'])
    s0.require(set(values) == set(authorized), 'Inner truth join mismatch')
    y = [values[(d,)]['y_audited_f'] for d, ok in zip(query.dates, mask) if ok]
    s0.require(all(type(v) is int and -40 <= v <= 120 for v in y), 'Invalid inner truth')
    return np.asarray(y)


def block_scores(directory, query, support, candidates, loader, run_sha):
    path = directory / 'SCORES.json'
    if not support['summary']['included']:
        result = {'status': 'EXCLUDED_TARGET_FREE_SUPPORT', 'losses': {}, 'invalid': {}, 'outcomes_read': False}
    else:
        paths = [directory / c['candidate_id'] for c in candidates]
        # On resume, verified unit digests pin cached scores to the exact predictions.
        units = {c['candidate_id']: verify_unit(p, run_sha, c)['record_sha256'] for c, p in zip(candidates, paths)}
        if path.exists():
            result = s0.read_json(path); s0.check_record(result)
            s0.require(result['units'] == units and result['support_sha256'] == digest(support), 'Score dependencies changed')
            return result
        mask = np.array(support['mask'], dtype=bool)
        y = inner_labels(loader, query, mask, paths, candidates, run_sha)
        losses = {}; invalid = {}; ids = [m['issue_state_id'] for m in query.metadata]
        for candidate, p in zip(candidates, paths):
            cid = candidate['candidate_id']; unit = s0.read_json(p / 'UNIT.json')
            if unit['status'] == 'INVALID_SOLVER':
                invalid[cid] = unit['reason']; continue
            rows = aligned_rows(p, ids, ['probabilities', 'status'])
            selected = [r for r, ok in zip(rows, mask) if ok]
            s0.require(all(r['status'] == 'AVAILABLE' for r in selected), 'Unexpected abstention on frozen common support')
            losses[cid] = day_losses([r['probabilities'] for r in selected], y, [d for d, ok in zip(query.dates, mask) if ok])
        result = {'status': 'INNER_DEVELOPMENT_SCORES', 'losses': losses, 'invalid': invalid,
                  'outcomes_read': True, 'units': units, 'support_sha256': digest(support)}
    result['record_sha256'] = digest(result)
    return freeze(path, result)


def eligible_inners(contract, outer):
    return [i for i in contract['folds']['inner'] if i['assessment_end'] <= outer['train_end']]


def select_outer(model, oid, candidates, blocks, run_sha):
    losses = {c['candidate_id']: {} for c in candidates}; invalid = {}; included = 0
    for block in blocks:
        support = s0.read_json(block / 'SUPPORT.json'); scores = s0.read_json(block / 'SCORES.json'); s0.check_record(scores)
        included += int(support['summary']['included'])
        invalid.update(scores['invalid'])
        for cid, values in scores['losses'].items():
            s0.require(not (set(losses[cid]) & set(values)), 'Overlapping inner assessment dates')
            losses[cid].update(values)
    selected, means = choose(candidates, losses, invalid) if included >= 2 else (None, {})
    return {'model_id': model, 'outer_fold_id': oid, 'selected': selected, 'inner_nll': means,
            'invalid_candidates': invalid, 'included_inner_blocks': included,
            'unsupported_reason': None if selected else ('INSUFFICIENT_TUNING_SUPPORT' if included < 2 else 'NO_VALID_CONFIGURATION'),
            'tuning_days': len(losses[selected['candidate_id']]) if selected else 0,
            'blocks': {str(p.name): s0.sha256(p / 'SCORES.json') for p in blocks},
            'run_binding_sha256': run_sha, 'outer_outcomes_used': False,
            'grid_boundary': {} if selected is None else {k: selected['parameters'][k] in (min(c['parameters'][k] for c in candidates), max(c['parameters'][k] for c in candidates)) for k in selected['parameters']}}


def baseline_partitions(experiment, oid):
    root = experiment / 'runs' / BASELINE
    release = s0.read_json(root / 'BASELINE_RELEASE.json'); s0.check_record(release)
    output = {}
    for model in ['B0_H', 'B0_Q']:
        rel = f'units/{oid}_OUTER_{model}'; path = root / rel
        s0.require(s0.sha256(path / 'unit.json') == release['units'][rel], 'Baseline unit changed')
        unit = s0.read_json(path / 'unit.json'); s0.check_record(unit)
        s0.require(s0.sha256(path / 'forecast/manifest.json') == unit['forecast_manifest_sha256'], 'Baseline manifest changed')
        m = s0.read_json(path / 'forecast/manifest.json'); s0.check_record(m)
        s0.require(s0.sha256(path / 'forecast/predictions.parquet') == m['predictions_sha256'], 'Baseline predictions changed')
        output[model] = path
    return output


def finalize(run, experiment, contract, run_sha, identity, implementation, project):
    outer_records = {}; coverage = {}; unsupported = []
    for outer in contract['folds']['outer']:
        oid = outer['outer_fold_id']; paths = baseline_partitions(experiment, oid)
        for model in MODELS:
            path = run / 'outer' / f'{oid}_{model}'
            unit = verify_unit(path, run_sha)
            s0.require(unit['status'] == 'PREDICTIONS_FROZEN', 'Missing outer predictions')
            if unit['unsupported_reason']: unsupported.append({'outer': oid, 'model': model, 'reason': unit['unsupported_reason']})
            paths[model] = path
        first = pq.read_table(paths['B0_Q'] / 'forecast/predictions.parquet', columns=['issue_state_id', 'target_date']).to_pylist()
        ids = [r['issue_state_id'] for r in first]; dates = [r['target_date'] for r in first]
        masks = {}; coverage[oid] = {}
        for model, path in paths.items():
            rows = aligned_rows(path, ids, ['status'])
            masks[model] = np.array([r['status'] == 'AVAILABLE' for r in rows])
            coverage[oid][model] = support_summary(dates, masks[model])
            outer_records[f'{oid}/{model}'] = {'path': os.path.relpath(path, run),
                'forecast_manifest_sha256': s0.sha256(path / 'forecast/manifest.json'),
                'predictions_sha256': s0.sha256(path / 'forecast/predictions.parquet')}
        common = np.logical_and.reduce([masks[m] for m in ['B0_H', 'B0_Q', 'ANEN', 'GAM_LS_NORMAL']])
        coverage[oid]['primary_common'] = support_summary(dates, common)
        freeze(run / f'{oid}_common_support.json', {'expected_issue_ids': ids, 'mask': common.tolist(), 'outcomes_used': False})
    s0.require(binding(implementation, experiment, project) == identity, 'Implementation changed during run')
    artifacts = {p.relative_to(run).as_posix(): s0.sha256(p) for pattern in ['inner/*/SUPPORT.json', 'inner/*/SCORES.json', 'inner/*/*/UNIT.json', 'outer/*/UNIT.json', 'selections/*.json', '*_common_support.json'] for p in run.glob(pattern)}
    return seal(run / 'COMPARISON_RELEASE.json', {'schema': 'R14_S4_COMPARISON_RELEASE_V1',
        'status': 'FROZEN_WITH_UNSUPPORTED_MODELS' if unsupported else 'FROZEN',
        'run_binding_sha256': run_sha, 'outer_partitions': outer_records, 'artifacts': artifacts,
        'coverage': coverage, 'unsupported_models': unsupported,
        'outer_scores_computed': False, 'reserved_or_tail_outcomes_returned': False,
        'historical_outer_evidence': 'Baseline outcomes previously inspected; development comparison, not fresh blind evidence.',
        'market_evaluation_performed': False})


def run(implementation, experiment, project, directory, max_new_units=None):
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / 'run.lock').open('a+') as lock:
        try: fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError: raise s0.ContractError('Another process owns this run')
        return _run(implementation, experiment, project, directory, max_new_units)


def _run(implementation, experiment, project, directory, max_new_units):
    identity = binding(implementation, experiment, project); run_sha = digest(identity)
    freeze(directory / 'run.json', identity)
    s3 = experiment / 'implementations/s3_v1'; loader = Loader(project, experiment, s3)
    contract = loader.contract; registry = s0.read_json(s3 / 'candidates.json')
    completed = 0; new = 0; started = time.monotonic(); interrupted = [False]; timings = {}
    total = len(contract['folds']['inner']) * len(registry) + len(contract['folds']['outer']) * len(MODELS)
    previous = {sig: signal.signal(sig, lambda *_: interrupted.__setitem__(0, True)) for sig in [signal.SIGINT, signal.SIGTERM]}
    def status(state, current=None):
        value = {'state': state, 'pid': os.getpid(), 'completed_candidate_decisions': completed,
                 'total_candidate_decisions': total, 'new_units_this_invocation': new, 'current': current,
                 'updated_utc': __import__('datetime').datetime.now(__import__('datetime').timezone.utc).isoformat(),
                 'elapsed_this_invocation_seconds': time.monotonic()-started,
                 'recent_unit_seconds_by_model': timings, 'outer_scores_computed': False,
                 'progress_note': 'Counts include target-free excluded candidates; resumed checkpoints are counted as verified.'}
        write(directory / 'status.json', value)
        print(f'{state}: {completed}/{total} candidate decisions; {current or ""}', flush=True)
        return value
    def paused():
        if interrupted[0] or (directory / 'PAUSE').exists() or (max_new_units is not None and new >= max_new_units):
            status('PAUSED'); return True
        return False
    done_blocks = set()
    try:
        for outer in contract['folds']['outer']:
            oid = outer['outer_fold_id']
            for model in MODELS:
                candidates = [c for c in registry if c['model_id'] == model]; blocks = []
                for inner in eligible_inners(contract, outer):
                    iid = inner['inner_fold_id']; block = directory / 'inner' / f'{iid}_{model}'; blocks.append(block)
                    canonical = next(o['outer_fold_id'] for o in contract['folds']['outer'] if inner in eligible_inners(contract, o))
                    # Feature and training-label populations must match before reusing an inner fit.
                    for split in ['TRAIN', 'ASSESS']:
                        s0.require(loader.fold_dates(oid, split, iid) == loader.fold_dates(canonical, split, iid), 'Cannot reuse nonidentical inner fold')
                    if block in done_blocks: continue
                    if paused(): return s0.read_json(directory / 'status.json')
                    status('LOADING', f'{iid}/{model}')
                    train = loader.load_features(model, canonical, 'TRAIN', iid)
                    query = loader.load_features(model, canonical, 'ASSESS', iid)
                    common = common_support(train, query, candidates, loader.s3)
                    support = {'summary': support_summary(query.dates, common), 'mask': common.tolist(),
                               'expected_issue_ids_sha256': digest([m['issue_state_id'] for m in query.metadata]),
                               'canonical_outer': canonical, 'inner': iid, 'model': model,
                               'outcomes_used': False, 'candidate_registry_sha256': digest(candidates)}
                    freeze(block / 'SUPPORT.json', support)
                    if support['summary']['included']:
                        y = None; analog = None; artifact_template = None
                        for candidate in candidates:
                            if paused(): return s0.read_json(directory / 'status.json')
                            path = block / candidate['candidate_id']; existed = path.exists()
                            status('FITTING_AND_PREDICTING' if not existed else 'CHECKING_CHECKPOINT', f'{iid}/{candidate["candidate_id"]}')
                            if not existed:
                                if y is None: y = loader.training_labels(train)
                                if model == 'ANEN' and analog is None: analog = runtime.fit(train, y, loader.s3, candidate['parameters'])
                            record = make_unit(path, train, query, y, candidate, loader.s3, s3, loader, run_sha,
                                               as_date(inner['assessment_start'])-timedelta(days=2), shared_fit=analog, artifact_template=artifact_template)
                            if model == 'ANEN' and record['status'] == 'PREDICTIONS_FROZEN' and artifact_template is None: artifact_template = path
                            completed += 1
                            if not existed: new += 1; timings[model] = record['seconds']
                        if paused(): return s0.read_json(directory / 'status.json')
                        status('SCORING_INNER_ONLY', f'{iid}/{model}')
                    else: completed += len(candidates)
                    block_scores(block, query, support, candidates, loader, run_sha)
                    done_blocks.add(block)
                selection = select_outer(model, oid, candidates, blocks, run_sha)
                freeze(directory / 'selections' / f'{oid}_{model}.json', selection)
                if paused(): return s0.read_json(directory / 'status.json')
                status('FITTING_OUTER', f'{oid}/{model}')
                train = loader.load_features(model, oid, 'TRAIN'); query = loader.load_features(model, oid, 'ASSESS')
                path = directory / 'outer' / f'{oid}_{model}'; existed = path.exists()
                y = None if existed or selection['unsupported_reason'] else loader.training_labels(train)
                record = make_unit(path, train, query, y, selection['selected'], loader.s3, s3, loader, run_sha,
                                   as_date(outer['assessment_start'])-timedelta(days=2), unsupported=selection['unsupported_reason'])
                completed += 1
                if not existed: new += 1; timings[model] = record['seconds']
        status('FREEZING_RELEASE')
        s0.require(completed == total, 'Incomplete candidate decision ledger')
        release = finalize(directory, experiment, contract, run_sha, identity, implementation, project)
        return status('COMPLETE_WITH_UNSUPPORTED_MODELS' if release['unsupported_models'] else 'COMPLETE')
    except Exception as exc:
        status('FAILED', str(exc)); raise
    finally:
        for sig, handler in previous.items(): signal.signal(sig, handler)


def validate_run(implementation, experiment, project, directory, deep=False):
    identity = binding(implementation, experiment, project)
    s0.require(identity == s0.read_json(directory / 'run.json'), 'Run binding changed')
    release = s0.read_json(directory / 'COMPARISON_RELEASE.json'); s0.check_record(release)
    s0.require(release['run_binding_sha256'] == digest(identity), 'Release binding mismatch')
    expected = {f'{o["outer_fold_id"]}/{m}' for o in s0.read_json(experiment / 'config/experiment.json')['folds']['outer'] for m in ['B0_H', 'B0_Q'] + MODELS}
    s0.require(set(release['outer_partitions']) == expected, 'Incomplete outer release')
    for rel, h in release['artifacts'].items():
        s0.require(s0.sha256(s0.safe_path(directory, rel)) == h, 'Release artifact changed: ' + rel)
    for record in release['outer_partitions'].values():
        path = (directory / record['path']).resolve()
        s0.require(path.is_relative_to(experiment / 'runs') or path.is_relative_to(directory), 'Invalid prediction path')
        s0.require(s0.sha256(path / 'forecast/manifest.json') == record['forecast_manifest_sha256'], 'Outer manifest changed')
        s0.require(s0.sha256(path / 'forecast/predictions.parquet') == record['predictions_sha256'], 'Outer predictions changed')
    if deep:
        from r14_s1.forecast import read_partition
        for path in directory.glob('inner/*/*/UNIT.json'):
            record = verify_unit(path.parent, digest(identity))
            if record['status'] == 'PREDICTIONS_FROZEN': read_partition(path.parent / 'forecast')
        for record in release['outer_partitions'].values(): read_partition(directory / record['path'] / 'forecast')
    return {'status': 'VALID', 'scope': 'all inner bytes and PMF rows' if deep else 'release manifests and outer prediction bytes', 'outer_scores_computed': False}
