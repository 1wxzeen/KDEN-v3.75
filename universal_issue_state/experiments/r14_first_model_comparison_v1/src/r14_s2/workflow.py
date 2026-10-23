"""Immutable candidate checkpoints, nested tuning, and baseline-only release."""
from datetime import timedelta
from pathlib import Path
import json,os,platform,time,shutil,tempfile,signal
import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
import s0,s1
from r14_s1.data import DevelopmentLoader,read_dates,unique_rows,as_date
from r14_s1.forecast import publish_partition,read_partition
from .model import ResidualFit,digest,support_summary,day_losses,choose


def write_json(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    temp=path.with_name(path.name+'.tmp')
    temp.write_text(json.dumps(value,indent=2,sort_keys=True)+'\n');os.replace(temp,path)


def seal(path,value):
    value=dict(value);value['record_sha256']=digest(value)
    write_json(path,value);return value


def code_identity(experiment):
    return {p.relative_to(experiment).as_posix():s0.sha256(p) for p in sorted((experiment/'src').rglob('*.py'))}


def binding(experiment,project,engine):
    s1.validate(experiment,project)
    release=s0.read_json(experiment/'manifests/S2_IMPLEMENTATION_RELEASE.json');s0.check_record(release)
    for rel,h in release['artifact_hashes'].items():
        s0.require(s0.sha256(s0.safe_path(experiment,rel))==h,'S2 implementation changed: '+rel)
    import pyarrow
    s0.require(np.__version__=='2.0.2' and pyarrow.__version__=='23.0.0','Use the registered numpy/pyarrow environment')
    env={'python':platform.python_version(),'numpy':np.__version__,'pyarrow':pyarrow.__version__,'platform':platform.platform(),'engine':engine}
    if engine=='scipy':
        import scipy
        env['scipy']=scipy.__version__
        s0.require(scipy.__version__=='1.15.3','S2 requires registered scipy 1.15.3')
    return {'schema':'R14_S2_RUN_V1','s1_release_sha256':s0.sha256(experiment/'manifests/S1_RELEASE.json'),
            's2_release_sha256':s0.sha256(experiment/'manifests/S2_IMPLEMENTATION_RELEASE.json'),
            'code':code_identity(experiment),'environment':env,'engine':engine,
            'input_inventory_sha256':s0.sha256(experiment/'manifests/input_inventory.json'),
            'config':{p.name:s0.sha256(p) for p in sorted((experiment/'config').glob('*.json'))}}


def inner_labels(loader,batch,partitions,mask):
    """Only included inner-assessment rows after EVERY candidate prediction is sealed."""
    s0.require(batch.split=='ASSESS' and batch.inner_fold_id is not None,'Outer scoring forbidden in S2')
    expected={r['issue_state_id'] for r in batch.metadata}
    for path in partitions:
        manifest,rows=read_partition(path)
        s0.require(manifest['inner_fold_id']==batch.inner_fold_id and manifest['outer_fold_id']==batch.outer_fold_id and manifest['model_id']==batch.model_id,'Inner prediction identity mismatch')
        s0.require({r['issue_state_id'] for r in rows}==expected,'Inner predictions incomplete')
    candidates=[c for c in s0.read_json(loader.experiment/'config/candidates.json')['candidates'] if c['model_id']==batch.model_id]
    s0.require(len(partitions)==len(candidates) and {s0.read_json(Path(p)/'manifest.json')['configuration_sha256'] for p in partitions}=={digest(c) for c in candidates},'Unsealed candidate set')
    dates=sorted({d for d,ok in zip(batch.dates,mask) if ok})
    s0.require(set(dates)<=set(loader.fold_dates(batch.outer_fold_id,'ASSESS',batch.inner_fold_id)),'Inner labels outside fold')
    t=loader.supplement['truth_accessor']
    catalog=read_dates(loader._input(t['catalog']),t['catalog_authorization_columns'],dates).to_pylist()
    authorized=unique_rows(catalog,['target_date'])
    s0.require(set(authorized)=={(d,) for d in dates},'Truth authorization missing')
    for r in catalog:
        s0.require(r['truth_group']=='development' and r['label_available_for_supervised_use'] is True and r['source_artifact_path']==t['source_path'] and r['source_artifact_sha256']==t['source_sha256'],'Unauthorized inner truth source')
    source=loader._input(t['source_path'])
    sd=pq.ParquetFile(source).read(columns=['target_date'])['target_date'].to_pylist()
    s0.require(max(sd)<=as_date(t['source_max_date']),'Source contains reserved/tail dates')
    values=unique_rows(read_dates(source,['target_date','y_audited_f'],dates).to_pylist(),['target_date'])
    s0.require(set(values)==set(authorized),'Inner truth join mismatch')
    y=[values[(d,)]['y_audited_f'] for d,ok in zip(batch.dates,mask) if ok]
    s0.require(all(type(v) is int and -40<=v<=120 for v in y),'Invalid inner truth')
    return np.array(y)


def forecast_records(fit,query,candidate,code_sha,inputs,engine,cutoff=None):
    train=fit.batch
    cutoff=cutoff or min(query.dates)-timedelta(days=2)
    for m,center,p,reason,diag in fit.forecast(query,candidate['parameters'],engine):
        r={k:m[k] for k in ['issue_state_id','target_date','statistical_group_id','issue_time_utc','local_minutes_since_0200','issue_count_for_target_day']}
        r.update(model_id=query.model_id,outer_fold_id=query.outer_fold_id,inner_fold_id=query.inner_fold_id,
                 status='ABSTAIN' if reason else 'AVAILABLE',abstention_reason=reason,
                 probabilities=None if p is None else p.tolist(),point_f=None if p is None else center+diag['residual_mean_f'],
                 baseline_center_f=center,training_start=min(train.dates),training_end=max(train.dates),label_cutoff=cutoff,
                 configuration_sha256=digest(candidate),code_sha256=code_sha,input_hashes_json=json.dumps(inputs,sort_keys=True),diagnostics_json=json.dumps(diag,sort_keys=True))
        yield r


def verify_unit(path,expected_ids=None,configuration=None):
    record=s0.read_json(path/'unit.json');s0.check_record(record)
    s0.require(s0.sha256(path/'fit.parquet')==record['fit_sha256'],'Fit changed')
    manifest,rows=read_partition(path/'forecast')
    s0.require(manifest['configuration_sha256']==digest(record['candidate']),'Fit/candidate identity mismatch')
    s0.require(all(r['configuration_sha256']==manifest['configuration_sha256'] and r['code_sha256']==manifest['code_sha256'] and json.loads(r['input_hashes_json'])==manifest['input_hashes'] for r in rows),'Row lineage mismatch')
    s0.require(s0.sha256(path/'forecast/manifest.json')==record['forecast_manifest_sha256'],'Forecast manifest changed')
    if expected_ids is not None:s0.require({r['issue_state_id'] for r in rows}==set(expected_ids),'Checkpoint key set mismatch')
    if configuration is not None:s0.require(manifest['configuration_sha256']==digest(configuration),'Checkpoint candidate mismatch')
    return record,rows


def create_unit(path,fit,query,candidate,identity,engine):
    ids=[m['issue_state_id'] for m in query.metadata]
    if path.exists():
        result=verify_unit(path,ids,candidate)[0]
        s0.require(result['run_binding_sha256']==identity['run_sha'],'Unit belongs to another run')
        return result
    # Whole fit + prediction pair committed with one rename. Interrupted scratch is never reused.
    scratch=Path(tempfile.mkdtemp(prefix='.unit-',dir=path.parent));started=time.monotonic()
    try:
        pq.write_table(pa.Table.from_pylist(fit.artifact_rows()),scratch/'fit.parquet')
        publish_partition(scratch/'forecast',forecast_records(fit,query,candidate,identity['code_sha'],identity['inputs'],engine,identity.get('cutoff')),ids)
        result=seal(scratch/'unit.json',{'candidate':candidate,'run_binding_sha256':identity['run_sha'],
             'fit_sha256':s0.sha256(scratch/'fit.parquet'),'forecast_manifest_sha256':s0.sha256(scratch/'forecast/manifest.json'),
             'seconds':time.monotonic()-started,'rows':len(ids),'training_days':len(set(fit.batch.dates)),
             'fit_note':'Training residuals; not out-of-sample predictions','inputs':identity['inputs']})
        os.rename(scratch,path);return result
    finally:
        if scratch.exists():shutil.rmtree(scratch)


def run(experiment,project,root,engine='scipy',max_units=None):
    import fcntl
    root=Path(root);root.mkdir(parents=True,exist_ok=True)
    # OS lock is released after crashes; the lock file itself is harmless.
    with (root/'run.lock').open('a+') as lock:
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:raise s0.ContractError('Another process owns this run')
        return _run(experiment,project,root,engine,max_units)


def _run(experiment,project,root,engine,max_units):
    identity=binding(experiment,project,engine);run_sha=digest(identity);code_sha=digest(identity['code'])
    if (root/'run.json').exists():s0.require(s0.read_json(root/'run.json')==identity,'Run identity changed; start a new run')
    else:write_json(root/'run.json',identity)
    loader=DevelopmentLoader(project,experiment);contract=loader.contract
    all_candidates=s0.read_json(experiment/'config/candidates.json')['candidates']
    # 360 inner configuration partitions plus six selected outer partitions.
    total=366;completed=0;new=0;started=time.monotonic();durations=[];unit_paths=[];selections=[]
    interrupted=[False]
    old={sig:signal.signal(sig,lambda *_:interrupted.__setitem__(0,True)) for sig in [signal.SIGINT,signal.SIGTERM]}
    def status(state,unit=None):
        write_json(root/'status.json',{'state':state,'completed_units':completed,'total_units':total,'current_unit':unit,
                   'elapsed_this_invocation_seconds':time.monotonic()-started,'pid':os.getpid(),
                   'eta_seconds':float(np.mean(durations)*(total-completed)) if durations else None,
                   'eta_note':'Approximate; pool sizes and block lengths vary','outer_scores_computed':False})
    def check_pause():
        if interrupted[0] or (root/'PAUSE').exists() or (max_units is not None and new>=max_units):
            status('PAUSED');return True
        return False
    def unit(path,fit,query,candidate):
        nonlocal new,completed
        if check_pause():return False
        status('RUNNING',str(path.relative_to(root)))
        existed=path.exists()
        spec=next(s for s in contract['folds']['inner' if query.inner_fold_id else 'outer'] if s.get('inner_fold_id',s.get('outer_fold_id'))==(query.inner_fold_id or query.outer_fold_id))
        cutoff=as_date(spec['assessment_start'])-timedelta(days=2)
        record=create_unit(path,fit,query,candidate,{'run_sha':run_sha,'code_sha':code_sha,'inputs':loader.input_hashes(),'cutoff':cutoff},engine)
        completed+=1;unit_paths.append(str(path.relative_to(root)))
        if not existed:new+=1;durations.append(record['seconds'])
        status('RUNNING');return True
    try:
        (root/'units').mkdir(exist_ok=True)
        for outer in contract['folds']['outer']:
            oid=outer['outer_fold_id']
            inners=[i for i in contract['folds']['inner'] if i['assessment_end']<=outer['train_end']]
            for model in ['B0_H','B0_Q']:
                candidates=[c for c in all_candidates if c['model_id']==model]
                scores={c['candidate_id']:{} for c in candidates};support=[]
                for inner in inners:
                    if check_pause():return
                    iid=inner['inner_fold_id'];status('LOADING',f'{oid}/{model}/{iid}')
                    train=loader.load_features(model,oid,'TRAIN',iid);labels=loader.training_labels(train)
                    query=loader.load_features(model,oid,'ASSESS',iid);fit=ResidualFit(train,labels)
                    masks=[query.available & (fit.counts(query,c['parameters']['seasonal_half_width_days'])>=40) for c in candidates]
                    common=np.logical_and.reduce(masks);summary=support_summary(query.dates,common);summary['inner_fold_id']=iid
                    support.append(summary)
                    support_path=root/f'{oid}_{model}_{iid}_support.json'
                    support_record={'summary':summary,'mask_sha256':digest(common.tolist()),'issue_ids_sha256':digest([m['issue_state_id'] for m in query.metadata]),'outcomes_used':False}
                    if support_path.exists():s0.require(s0.read_json(support_path)==support_record,'Support changed on resume')
                    else:write_json(support_path,support_record)
                    paths=[]
                    for c in candidates:
                        path=root/'units'/f'{oid}_{iid}_{c["candidate_id"]}'
                        if not unit(path,fit,query,c):return
                        paths.append(path/'forecast')
                    if summary['included']:
                        y=inner_labels(loader,query,paths,common)
                        for c,path in zip(candidates,paths):
                            _,rows=read_partition(path)
                            p=[r['probabilities'] for r,ok in zip(rows,common) if ok]
                            dates=[d for d,ok in zip(query.dates,common) if ok]
                            losses=day_losses(p,y,dates)
                            s0.require(not(set(scores[c['candidate_id']])&set(losses)),'Overlapping inner assessment days')
                            scores[c['candidate_id']].update(losses)
                s0.require(sum(s['included'] for s in support)>=2,'INSUFFICIENT_TUNING_SUPPORT; no baseline selected')
                chosen,means=choose(candidates,scores)
                selection={'model_id':model,'outer_fold_id':oid,'selected':chosen,'inner_nll':means,'support':support,
                  'tuning_days':len(next(iter(scores.values()))),'run_binding_sha256':run_sha,
                  'selection_note':'Development tuning evidence; no outer outcomes used',
                  'grid_boundary':{k:chosen['parameters'][k] in (min(c['parameters'][k] for c in candidates),max(c['parameters'][k] for c in candidates)) for k in chosen['parameters']}}
                sp=root/f'{oid}_{model}_selection.json'
                if sp.exists():s0.require(s0.read_json(sp)==selection,'Selection changed on resume')
                else:write_json(sp,selection)
                selections.append(str(sp.relative_to(root)))
                if check_pause():return
                status('LOADING',f'{oid}/{model}/outer')
                train=loader.load_features(model,oid);labels=loader.training_labels(train)
                query=loader.load_features(model,oid,'ASSESS');fit=ResidualFit(train,labels)
                if not unit(root/'units'/f'{oid}_OUTER_{model}',fit,query,chosen):return
        status('VALIDATING')
        inventory={rel:s0.sha256(root/rel/'unit.json') for rel in unit_paths}
        for rel in unit_paths:verify_unit(root/rel)
        s0.require(set(inventory)==expected_units(experiment),'Incomplete expected units')
        s0.require(identity==binding(experiment,project,engine),'Implementation changed during run')
        artifact_files={p.relative_to(root).as_posix():s0.sha256(p) for p in root.glob('*_support.json')}
        artifact_files.update({rel:s0.sha256(root/rel) for rel in selections})
        seal(root/'BASELINE_RELEASE.json',{'status':'S2_BASELINES_FROZEN','run_binding_sha256':run_sha,'units':inventory,
              'artifacts':artifact_files,'outer_scores_computed':False,'reserved_or_tail_outcomes_returned':False,
              'synthetic_bands_are_market_listings':False,'comparison_release_complete':False})
        status('COMPLETE')
    except Exception as exc:
        status('FAILED',str(exc));raise
    finally:
        for sig,handler in old.items():signal.signal(sig,handler)


def expected_units(experiment):
    contract=s0.read_json(experiment/'config/experiment.json')
    candidates=s0.read_json(experiment/'config/candidates.json')['candidates']
    names=set()
    for outer in contract['folds']['outer']:
        oid=outer['outer_fold_id']
        for model in ['B0_H','B0_Q']:
            names.add(f'units/{oid}_OUTER_{model}')
            for inner in contract['folds']['inner']:
                if inner['assessment_end']<=outer['train_end']:
                    for c in candidates:
                        if c['model_id']==model:names.add(f'units/{oid}_{inner["inner_fold_id"]}_{c["candidate_id"]}')
    return names


def validate_run(experiment,project,root):
    root=Path(root);identity=s0.read_json(root/'run.json')
    s0.require(identity==binding(experiment,project,identity['engine']),'Current inputs/code differ from run')
    release=s0.read_json(root/'BASELINE_RELEASE.json');s0.check_record(release)
    s0.require(release['run_binding_sha256']==digest(identity),'Release binding changed')
    s0.require(set(release['units'])==expected_units(experiment),'Incomplete baseline release')
    rows=0
    for rel,h in release['units'].items():
        path=s0.safe_path(root,rel)
        s0.require(s0.sha256(path/'unit.json')==h,'Unit manifest changed')
        unit,records=verify_unit(path);rows+=len(records)
        s0.require(unit['run_binding_sha256']==digest(identity),'Unit run mismatch')
    for rel,h in release['artifacts'].items():s0.require(s0.sha256(s0.safe_path(root,rel))==h,'Selection/support changed')
    return {'status':'VALID','units':366,'prediction_rows':rows,'outer_scores_computed':False}
