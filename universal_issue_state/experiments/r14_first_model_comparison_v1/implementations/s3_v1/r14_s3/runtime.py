"""S3 single-unit publication. S4 owns nested candidate selection/orchestration."""
from pathlib import Path
from datetime import timedelta
import hashlib,json,os,tempfile,shutil,time,platform
import numpy as np
import scipy,pyarrow as pa,pyarrow.parquet as pq
import s0,s1
from r14_s1.forecast import publish_partition
from .data import Loader
from .anen import Analog
from .gam import GAM

MODELS=['ANEN','GAM_LS_NORMAL','GAM_LOCATION_NORMAL','GAM_LS_T5']
def digest(obj):return hashlib.sha256(s0.canonical(obj)).hexdigest()
def save(path,obj):Path(path).write_text(json.dumps(obj,indent=2,sort_keys=True,allow_nan=False)+'\n')
def candidates(root,model):return [c for c in s0.read_json(root/'candidates.json') if c['model_id']==model]
def fit(batch,y,config,parameters):return Analog(batch,y,config) if batch.model_id=='ANEN' else GAM(batch,y,config,parameters)

def validate(root,experiment,project,release=True):
    s1.validate(experiment,project)
    cfg=s0.read_json(root/'config.json')
    s0.require(np.__version__=='2.0.2' and scipy.__version__=='1.15.3' and pa.__version__=='23.0.0','Use pinned modeling environment')
    for p,h in [(experiment/'manifests/S1_RELEASE.json',cfg['parent_s1_sha256']),(experiment/'manifests/S2_IMPLEMENTATION_RELEASE.json',cfg['parent_s2_sha256']),(project/cfg['registry'],cfg['registry_sha256']),(experiment/'diagnostics/s2_baseline_review_v1/EXPOSURE.json',cfg['exposure_sha256']),(experiment/'runs/r14-s2-20260925T185129Z/BASELINE_RELEASE.json',cfg['baseline_release_sha256'])]:s0.require(s0.sha256(p)==h,'S3 parent/source mismatch: '+str(p))
    if release:
        m=s0.read_json(root/'RELEASE.json');s0.check_record(m)
        for rel,h in m['files'].items():s0.require(s0.sha256(s0.safe_path(root,rel))==h,'S3 release file changed: '+rel)
    return {'status':'VALID_S3_IMPLEMENTATION','models':MODELS,'reserved_outcomes_read':False,'parameters_selected_by_this_check':False}

def identity(root,loader,model,parameters):
    cfg=s0.read_json(root/'config.json')
    return {'schema':'R14_S3_FIT_IDENTITY_V1','model':model,'parameters':parameters,'configuration_sha256':digest({'spec':cfg,'parameters':parameters,'model':model}),
            'code_sha256':digest({p.relative_to(root).as_posix():s0.sha256(p) for p in sorted(root.rglob('*.py'))}),
            'release_sha256':s0.sha256(root/'RELEASE.json'),'input_hashes':loader.input_hashes(),
            'environment':{'python':platform.python_version(),'numpy':np.__version__,'scipy':scipy.__version__,'pyarrow':pa.__version__,'platform':platform.platform(),'OPENBLAS_NUM_THREADS':os.environ.get('OPENBLAS_NUM_THREADS'),'OMP_NUM_THREADS':os.environ.get('OMP_NUM_THREADS')}}

def records(fitted,query,parameters,ident,cutoff):
    for m,c,p,point,reason,diag in fitted.forecast(query,parameters):
        record={k:m[k] for k in ['issue_state_id','target_date','statistical_group_id','issue_time_utc','local_minutes_since_0200','issue_count_for_target_day']}
        record.update(model_id=query.model_id,outer_fold_id=query.outer_fold_id,inner_fold_id=query.inner_fold_id,status='ABSTAIN' if reason else 'AVAILABLE',abstention_reason=reason,probabilities=None if p is None else p.tolist(),point_f=point,baseline_center_f=c,training_start=min(fitted.batch.dates),training_end=max(fitted.batch.dates),label_cutoff=cutoff,
                      configuration_sha256=ident['configuration_sha256'],code_sha256=ident['code_sha256'],input_hashes_json=json.dumps(ident['input_hashes'],sort_keys=True),diagnostics_json=json.dumps(diag,sort_keys=True))
        yield record

def fit_artifact(root,fitted,y,ident):
    batch=fitted.batch
    np.savez_compressed(root/'training.npz',X=batch.X,y=np.asarray(y),available=batch.available)
    save(root/'training_metadata.json',{'columns':batch.columns,'rows':[{k:str(v) if hasattr(v,'isoformat') else v for k,v in m.items()} for m in batch.metadata]})
    # Sufficient fitted state for application without an untrusted pickle.
    if isinstance(fitted,GAM):
        state={'theta':fitted.theta.tolist(),'selected_start':fitted.selected_start,'starts':fitted.starts,'family':fitted.family}
        for key in ['location','scale']:
            design=getattr(fitted,key);state[key]={'blocks':design.blocks,'mean':design.mean.tolist(),'rms':design.rms.tolist(),'keep':design.keep.tolist(),'constant':design.constant}
    else:
        state={'groups':{str(k):{n:(v.tolist() if isinstance(v,np.ndarray) else v) for n,v in g.items()} for k,g in fitted.groups.items()},'reference_cache_policy':'Recompute leave-one-day-out references from saved training groups; these are diagnostics, not validation forecasts.'}
    save(root/'fit_state.json',state);save(root/'identity.json',ident)

def unit(root,experiment,project,destination,model,candidate_id,outer,inner=None):
    import fcntl
    validate(root,experiment,project);cs=candidates(root,model)
    candidate=next((x for x in cs if x['candidate_id']==candidate_id),None);s0.require(candidate is not None,'Unknown registered candidate ID')
    destination=Path(destination);destination.parent.mkdir(parents=True,exist_ok=True)
    status_path=destination.with_suffix('.status.json')
    def status(state):
        tmp=status_path.with_suffix('.tmp');save(tmp,{'state':state,'pid':os.getpid(),'model':model,'candidate_id':candidate_id,'outer':outer,'inner':inner,'elapsed_seconds':time.monotonic()-started,'eta_seconds':None,'unit':'one complete fit and forecast partition','outcome_scores_computed':False});os.replace(tmp,status_path)
    started=time.monotonic()
    with destination.with_suffix('.lock').open('a+') as lock:
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:raise s0.ContractError('Unit is already running')
        s0.require(not destination.exists(),'Unit exists; validate it or choose a new destination. Never overwrite fits.')
        loader=Loader(project,experiment,root);started=time.monotonic();scratch=Path(tempfile.mkdtemp(prefix='.s3-unit-',dir=destination.parent))
        try:
            status('LOADING');train=loader.load_features(model,outer,'TRAIN',inner);y=loader.training_labels(train);query=loader.load_features(model,outer,'ASSESS',inner)
            status('FITTING');ident=identity(root,loader,model,candidate['parameters']);fitted=fit(train,y,loader.s3,candidate['parameters']);fit_artifact(scratch,fitted,y,ident)
            spec=next(x for x in loader.contract['folds']['inner' if inner else 'outer'] if x.get('inner_fold_id',x.get('outer_fold_id'))==(inner or outer))
            cutoff=__import__('datetime').date.fromisoformat(spec['assessment_start'])-timedelta(days=2)
            status('PREDICTING');publish_partition(scratch/'forecast',records(fitted,query,candidate['parameters'],ident,cutoff),[m['issue_state_id'] for m in query.metadata])
            artifact={'status':'S3_CANDIDATE_UNIT_COMPLETE_NOT_SELECTED','outer':outer,'inner':inner,'candidate':candidate,'seconds':time.monotonic()-started,'files':{p.relative_to(scratch).as_posix():s0.sha256(p) for p in scratch.rglob('*') if p.is_file()},'outcome_scores_computed':False}
            artifact['record_sha256']=digest(artifact);save(scratch/'UNIT.json',artifact);os.rename(scratch,destination);status('COMPLETE')
            return artifact
        except BaseException as exc:
            status('INTERRUPTED' if isinstance(exc,KeyboardInterrupt) else 'FAILED')
            save(destination.with_suffix('.failure.json'),{'error':str(exc),'starts':getattr(exc,'starts',[]),'no_unit_committed':True});raise
        finally:
            if scratch.exists():shutil.rmtree(scratch)

def load_fit(directory,config):
    """Restore checked JSON/NPZ state without refitting or executing a pickle."""
    from datetime import date,datetime
    from r14_s1.data import FeatureBatch
    from .design import Design
    directory=Path(directory);unit=s0.read_json(directory/'UNIT.json');s0.check_record(unit)
    for rel,h in unit['files'].items():s0.require(s0.sha256(s0.safe_path(directory,rel))==h,'Saved fit artifact changed')
    ident=s0.read_json(directory/'identity.json');model=ident['model'];params=ident['parameters']
    s0.require(ident['configuration_sha256']==digest({'spec':config,'parameters':params,'model':model}),'Fit configuration mismatch')
    meta=s0.read_json(directory/'training_metadata.json');rows=[]
    for record in meta['rows']:
        row=dict(record)
        for k in row:
            if k=='target_date':row[k]=date.fromisoformat(row[k])
            elif k.endswith('_utc') and isinstance(row[k],str):row[k]=datetime.fromisoformat(row[k])
        rows.append(row)
    with np.load(directory/'training.npz',allow_pickle=False) as a:
        X=a['X'].copy();available=a['available'].astype(bool)
    batch=FeatureBatch(model,tuple(meta['columns']),X,tuple(rows),available,tuple(tuple(n for n,v in zip(meta['columns'],r) if not np.isfinite(v)) for r in X),ident['input_hashes'],unit['outer'],unit['inner'],'TRAIN')
    state=s0.read_json(directory/'fit_state.json')
    if model=='ANEN':
        obj=Analog.__new__(Analog);obj.groups={int(k):{n:np.asarray(v,dtype=bool if n=='active' else int if n in ['ids','doy'] else float) for n,v in g.items()} for k,g in state['groups'].items()};obj.reference_cache={}
    else:
        obj=GAM.__new__(GAM);obj.theta=np.array(state['theta']);obj.selected_start=state['selected_start'];obj.starts=state['starts'];obj.family=state['family'];obj.model=model;obj.parameters=params
        for name in ['location','scale']:
            d=Design.__new__(Design);s=state[name];d.blocks=s['blocks'];d.mean=np.array(s['mean']);d.rms=np.array(s['rms']);d.keep=np.array(s['keep'],dtype=bool);d.constant=s['constant'];d.config=config;d.dimension=1+int(d.keep.sum());setattr(obj,name,d)
    obj.batch=batch;obj.config=config;return obj
