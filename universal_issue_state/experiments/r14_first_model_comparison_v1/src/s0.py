"""S0 validation only. Never decode truth or weather data pages; no fitting imports."""
from __future__ import annotations
import argparse
from collections import Counter
from datetime import date, timedelta
import hashlib
import json
from pathlib import Path
import sys

EXPERIMENT_ID = 'R14_FIRST_MODEL_COMPARISON_V1'
ROLE_COLS = ['target_date','statistical_group_id','evidence_role','supervised_eligible']
FOLD_COLS = ['outer_fold_id','target_date','statistical_group_id','assignment','supervised_assignment']

class ContractError(ValueError):
    pass

def require(ok, message):
    if not ok:
        raise ContractError(message)

def safe_path(root, name):
    p = Path(name)
    require(not p.is_absolute() and '..' not in p.parts, f'Unsafe relative path: {name}')
    root = Path(root).resolve()
    result = (root / p).resolve()
    require(result.is_relative_to(root), f'Path escapes root: {name}')
    return result

def read_json(path):
    return json.loads(Path(path).read_text())

def sha256(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for b in iter(lambda:f.read(1024*1024), b''):
            h.update(b)
    return h.hexdigest()

def canonical(value):
    return (json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=True)+'\n').encode()

def check_record(record):
    body = {k:v for k,v in record.items() if k!='record_sha256'}
    require(hashlib.sha256(canonical(body)).hexdigest()==record['record_sha256'], 'Invalid canonical record identity')

def exact_schema(document, schema):
    # The shipped Draft 2020-12 schemas deliberately use only type and const.
    # This is an exact-revision validator, not a general JSON Schema interpreter.
    require(set(schema)<= {'$schema','title','type','const'}, 'Unsupported schema keyword')
    require(schema.get('type')=='object' and isinstance(document,dict), 'Expected object')
    require(canonical(document)==canonical(schema['const']), 'Frozen contract/schema mismatch')

def check_partitions(partitions):
    for name,bands in partitions.items():
        observed=[]
        for b in bands:
            require(type(b['lower']) is int and type(b['upper']) is int and b['lower']<=b['upper'], 'Invalid integer band')
            observed.extend(range(b['lower'],b['upper']+1))
        require(observed==list(range(-40,121)), f'Partition overlap/gap/order: {name}')

def check_design(c, features, candidates, score):
    require(c['experiment_id']==EXPERIMENT_ID, 'Wrong experiment')
    require(c['access']['s0_truth_columns_allowed']==[] and not c['access']['reserved_outcomes_allowed'], 'Outcome access forbidden')
    require(c['access']['s0_truth_parquet_mode']=='OPAQUE_HASH_PLUS_SCHEMA_METADATA_NO_DATA_PAGES', 'Unsafe truth inventory mode')
    require(not c['execution']['s0_model_fits_allowed'], 'S0 cannot fit')
    require(c['truth']['publication_lag_target_days']==2, 'Label cutoff changed')
    require(not c['scope']['formal_promotion'], 'No promotion rule registered')
    for key, names in features['sets'].items():
        for name in names:
            require(name in features['registry_entries'], f'Unknown feature: {name}')
            require(not any(t in name.lower() for t in ['truth','label','market','kalshi','madis','fold','y_audited']), f'Forbidden predictor: {name}')
    require(set(c['anen']['features']) <= set(features['sets']['ANEN']), 'AnEn features mismatch')
    require(set(c['gam']['required_features'])==set(features['sets']['GAM']), 'GAM features mismatch')
    require(candidates['count']==len(candidates['candidates'])==232, 'Candidate count mismatch')
    ids=[r['candidate_id'] for r in candidates['candidates']]
    require(len(ids)==len(set(ids)), 'Duplicate candidate')
    require(Counter(r['model_id'] for r in candidates['candidates'])=={'B0_H':12,'B0_Q':12,'ANEN':180,'GAM_LS_NORMAL':12,'GAM_LOCATION_NORMAL':4,'GAM_LS_T5':12}, 'Candidate grid incomplete')
    require(c['selection']['coverages']==[1.0,0.75,0.5,0.25,0.1], 'Coverage grid changed')
    check_partitions(score['partitions'])

def metadata_folds(project, contract):
    import pyarrow.parquet as pq
    # Allowlisted role/fold metadata only. No truth catalog decode occurs here.
    root=Path(project)/'folds/kden_v375/v1'
    roles=pq.ParquetFile(root/'date_roles.parquet').read(columns=ROLE_COLS).to_pylist()
    outer=pq.ParquetFile(root/'outer_folds.parquet').read(columns=FOLD_COLS).to_pylist()
    inner=pq.ParquetFile(root/'inner_folds.parquet').read(columns=['inner_fold_id']+FOLD_COLS).to_pylist()
    require(len(roles)==2080 and len({r['target_date'] for r in roles})==2080, 'Date-role cardinality')
    require(len(outer)==6240 and len(inner)==31200,'Fold row count')
    role_by_date={r['target_date']:r for r in roles}
    dates=sorted(role_by_date)
    require(dates==[date(2021,1,1)+timedelta(days=i) for i in range(2080)],'Date-role range/gaps')
    require(len({r['statistical_group_id'] for r in roles})==2080,'Nonunique statistical groups')
    eligible=[r for r in roles if r['supervised_eligible']]
    require(len(eligible)==1707 and all(r['evidence_role']=='DEVELOPMENT_SUPERVISED' and r['target_date']<=date(2025,9,6) for r in eligible),'Development eligibility')
    require(sum(r['evidence_role']=='DEVELOPMENT_UNRESOLVED' for r in roles)==3,'Unresolved count')
    result=[]
    for is_inner,rows in [(False,outer),(True,inner)]:
        keys=['outer_fold_id','inner_fold_id'] if is_inner else ['outer_fold_id']
        groups={}
        unique=set()
        for row in rows:
            key=tuple(row[k] for k in keys)
            require((key,row['target_date']) not in unique,'Duplicate date assignment');unique.add((key,row['target_date']))
            require(row['statistical_group_id']==role_by_date[row['target_date']]['statistical_group_id'],'Group identity mismatch')
            if row['assignment'] in ['TRAIN','ASSESS']:
                require(role_by_date[row['target_date']]['supervised_eligible'],'Ineligible training/assessment date')
            groups.setdefault(key,[]).append(row)
        require(len(groups)==(15 if is_inner else 3),'Fold instance count')
        for key, group in sorted(groups.items()):
            spec=next(x for x in contract['folds']['inner' if is_inner else 'outer'] if x['inner_fold_id' if is_inner else 'outer_fold_id']==key[-1])
            if is_inner:
                enclosing=next(x for x in contract['folds']['outer'] if x['outer_fold_id']==key[0])
                require(spec['assessment_end']<=enclosing['train_end'],'Inner exceeds outer training')
            actual={tag:sorted(r['target_date'] for r in group if r['assignment']==tag) for tag in ['TRAIN','ASSESS']}
            for tag,start,end in [('TRAIN','train_start','train_end'),('ASSESS','assessment_start','assessment_end')]:
                expected=sorted(r['target_date'] for r in eligible if date.fromisoformat(spec[start])<=r['target_date']<=date.fromisoformat(spec[end]))
                require(actual[tag]==expected, f'Nominal assignment mismatch {key}/{tag}')
            require(max(actual['TRAIN'])<min(actual['ASSESS']),'Noncausal fold')
            cutoff=date.fromisoformat(spec['assessment_start'])-timedelta(days=2)
            kept=[d for d in actual['TRAIN'] if d<=cutoff]
            result.append({'fold_id':'/'.join(key),'type':'inner' if is_inner else 'outer','nominal_train_days':len(actual['TRAIN']),'label_lag_cutoff':str(cutoff),'lag_eligible_train_days':len(kept),'lag_excluded_dates':[str(d) for d in actual['TRAIN'] if d>cutoff],'assessment_days':len(actual['ASSESS'])})
    return {'role_counts':dict(Counter(r['evidence_role'] for r in roles)),'folds':result,'outcome_values_decoded':0,'columns_decoded':{'date_roles':ROLE_COLS,'outer':FOLD_COLS,'inner':['inner_fold_id']+FOLD_COLS}}

def validate(experiment, project, check_release=True):
    e=Path(experiment); p=Path(project)
    for name in ['experiment','features','scorecard','candidates','evidence_exposure','decisions']:
        exact_schema(read_json(e/f'config/{name}.json'),read_json(e/f'schemas/{name}.schema.json'))
    exact_schema(read_json(e/'environment/environment.json'),read_json(e/'schemas/environment.schema.json'))
    c=read_json(e/'config/experiment.json'); f=read_json(e/'config/features.json')
    check_design(c,f,read_json(e/'config/candidates.json'),read_json(e/'config/scorecard.json'))
    inv=read_json(e/'manifests/input_inventory.json')
    require(inv['verification_scope']=='selected_model_inputs_not_full_archive_reaudit','Wrong verification scope')
    for row in inv['files']:
        actual=safe_path(p,row['path'])
        require(actual.is_file(),f'Missing input: {row["path"]}')
        require(sha256(actual)==row['sha256'],f'Input changed: {row["path"]}')
        require(actual.stat().st_size==row['size_bytes'],f'Input size changed: {row["path"]}')
        if row.get('expected_upstream_sha256'):
            require(row['sha256']==row['expected_upstream_sha256'],f'Upstream identity mismatch: {row["path"]}')
    for row in inv['canonical_records']:
        check_record(read_json(safe_path(p,row)))
    p06=read_json(p/'state/PREFIT_P06_PASS.json');p07=read_json(p/'state/PREFIT_P07_PASS.json')
    boundary=read_json(p/'state/KDEN_V375_MODELING_BOUNDARY_PASS.json')
    require(p06['status']==p07['status']=='PASS','Upstream PASS absent')
    require(p07['predecessor_hashes']['PREFIT_P06']==p06['record_sha256']==boundary['p06_record_sha256'],'Broken predecessor chain')
    require(boundary['status']=='PREFIT_COMPLETE_MODEL_FITTING_AUTHORIZED','Wrong upstream boundary')
    require(boundary['model_fits_performed']==0 and not boundary['holdout_opened'],'Upstream boundary changed')
    require(sha256(p/'config/prefit/p07_rafm_experiment_v375.json')==boundary['p07_contract_sha256'],'P07 binding mismatch')
    require(sha256(p/'modeling/experiments/rafm_v1/manifests/p07_experiment_freeze.json')==boundary['p07_freeze_manifest_sha256'],'P07 freeze binding mismatch')
    actual_registry=read_json(p/f['source_registry']); indexed={r['name']:r for r in actual_registry['features']}
    require(len(indexed)==433,'Feature count')
    for name,entry in f['registry_entries'].items():
        require(indexed.get(name)==entry,f'Feature semantics differ: {name}')
    require(f['errata_overlay']==read_json(p/'config/prefit/p06_feature_contract_errata_v375.json'),'Errata overlay mismatch')
    metadata=metadata_folds(p,c)
    import pyarrow.parquet as pq
    total=0
    for row in inv['files']:
        if row.get('parquet_footer'):
            footer=pq.ParquetFile(safe_path(p,row['path']))
            require(footer.metadata.num_rows==row['parquet_footer']['rows'],'Footer row count changed')
            require(footer.schema_arrow.names==row['parquet_footer']['columns'],'Footer schema changed')
            if '/deterministic_features/' in row['path']:
                total+=footer.metadata.num_rows
                require(set(f['registry_entries'])<=set(footer.schema_arrow.names),'Feature partition missing required column')
    require(total==118536,'Feature row sum')
    if check_release:
        release=read_json(e/'manifests/S0_RELEASE.json');check_record(release)
        for name,digest in release['artifact_hashes'].items():
            require(sha256(safe_path(e,name))==digest,f'S0 artifact changed: {name}')
        require(release['status']=='S0_COMPLETE_S1_READY','Invalid S0 release status')
    return {'status':'VALID','experiment_id':EXPERIMENT_ID,'input_files_verified':len(inv['files']),'feature_columns':433,'feature_rows':total,'registered_configurations':232,'model_fits_performed':0,'outcome_values_decoded':0,'weather_data_pages_decoded':0,'reserved_outcomes_opened':False,'truth_file_handling':'opaque byte hash plus schema/row-count metadata; no truth data pages or outcome values decoded','validation_scope':inv['verification_scope'],'fold_metadata':metadata}

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project-root',type=Path,required=True)
    parser.add_argument('--experiment-root',type=Path,default=Path(__file__).resolve().parents[1])
    args=parser.parse_args()
    try:
        result=validate(args.experiment_root,args.project_root)
    except (ContractError,OSError,KeyError,ValueError) as exc:
        print(json.dumps({'status':'INVALID','reason':str(exc)}));return 1
    print(json.dumps(result,indent=2));return 0

if __name__=='__main__':
    sys.exit(main())
