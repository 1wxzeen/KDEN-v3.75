from pathlib import Path
import json,time,os,platform,fcntl
from datetime import datetime,timezone,date
import numpy as np
import scipy,pyarrow as pa,pyarrow.parquet as pq
import s0
from inputs import Context,save,seal,verify_record_file,digest
from boundaries import assert_eligible
from data import certificate,load,labels
from model import fit,predict,threshold,admit


def validate(E,root):
    release=s0.read_json(root/'RELEASE.json')
    for p,h in release['files'].items():s0.require(s0.sha256(root/p)==h,'CR1 implementation changed: '+p)
    cfg=s0.read_json(root/'config.json')
    for p,h in cfg['parents'].items():s0.require(s0.sha256(E/p)==h,'CR1 parent changed: '+p)
    sr=s0.read_json(E/'implementations/s6_v1/RELEASE.json')
    for p,h in sr['files'].items():s0.require(s0.sha256(E/'implementations/s6_v1'/p)==h,'S6 changed')
    reg=s0.read_json(E/'implementations/s6_v1/registration.json')
    for p,h in reg['parents'].items():s0.require(s0.sha256(E/p)==h,'Registered parent changed')
    s0.require(np.__version__=='2.0.2' and scipy.__version__=='1.15.3' and pa.__version__=='23.0.0','Use pinned model environment')
    return {'code_sha256':s0.sha256(root/'RELEASE.json'),'parents':cfg['parents'],'environment':{'python':platform.python_version(),'numpy':np.__version__,'scipy':scipy.__version__,'pyarrow':pa.__version__},'historical_not_blind':True}


def range_mask(dates,limits):return (dates>=limits[0])&(dates<=limits[1])

def verified_unit(path):
    r=verify_record_file(path/'UNIT.json')
    for p,h in r['files'].items():s0.require(s0.sha256(path/p)==h,'Completed CR1 unit changed')
    return r

def unit(E,out,data,ctx,reg,block,base,name,identity):
    path=out/'units'/f'{block["id"]}_{base}_{name}'
    if (path/'UNIT.json').exists():
        r=verified_unit(path);s0.require(r['binding']==digest(identity),'Wrong completed unit identity');return r
    path.mkdir(parents=True,exist_ok=True);dates=data['dates'];common=data['common']
    fm=range_mask(dates,block['fit'])&common;tm=range_mask(dates,block['threshold'])&common;am=range_mask(dates,block['assessment']);available=am&common
    assert_eligible(sorted(set(dates[fm])),block['threshold'][0],*reg['evidence']['historical_allowed'])
    assert_eligible(sorted(set(dates[tm])),block['assessment'][0],*reg['evidence']['historical_allowed'])
    start=time.monotonic()
    if name=='NATIVE':state={'reference':True};p=data['base'][base]['native'].copy()
    else:
        y=labels(ctx,data,fm,block['threshold'][0],reg);event=(data['base'][base]['integer']==y).astype(float)
        state=fit(data['designs'][base][name],event,dates,fm,reg);p=predict(state,data['designs'][base][name],common)
    thresholds={str(c):threshold(p,dates,data['expected'],tm,c,reg['chronology']['minimum_threshold_days']) for c in [1.,.5,.25,.1]}
    save(path/'fit.json',{'state':state,'base':base,'model':name,'fit_dates':sorted(set(dates[fm])),'preprocessing_dates':sorted(set(dates[fm])),'first_prediction_date':block['threshold'][0],'assessment_start':block['assessment'][0],'threshold_dates':sorted(set(dates[tm])),'thresholds':thresholds,'base_reuse_certificate_sha256':s0.sha256(out/'BASE_REUSE_CERTIFICATE.json'),'binding':digest(identity)})
    ii=np.where(am)[0];rows=[]
    for i in ii:
        a=bool(available[i]);row={'issue_state_id':data['ids'][i],'target_date':dates[i],'issue_minutes':int(data['minutes'][i]),'expected_issues':int(data['expected'][i]),'base_model':base,'reliability_model':name,'block':block['id'],'base_vintage':f'OUTER_0{int(dates[i][:4])-2022}','status':'AVAILABLE' if a else 'ABSTAIN_REQUIRED_INPUT','hit_probability':float(p[i]) if a else None,'base_integer':int(data['base'][base]['integer'][i]),'base_median':int(data['base'][base]['median'][i]),'B0_H_integer':int(data['base']['B0_H']['integer'][i]),'B0_Q_integer':int(data['base']['B0_Q']['integer'][i])}
        for c,t in thresholds.items():row['admit_'+c]=a and (t is None or p[i]>=t)
        rows.append(row)
    tmp=path/'predictions.parquet.tmp';pq.write_table(pa.Table.from_pylist(rows),tmp);os.replace(tmp,path/'predictions.parquet')
    # Threshold-block predictions are label-free and preserved for audit.
    ix=np.where(range_mask(dates,block['threshold']))[0]
    pq.write_table(pa.table({'issue_state_id':[data['ids'][i] for i in ix],'target_date':dates[ix].tolist(),'available':common[ix].tolist(),'hit_probability':[float(p[i]) if common[i] else None for i in ix],'expected_issues':data['expected'][ix]}),path/'threshold_predictions.parquet')
    return seal(path/'UNIT.json',{'status':'FROZEN','binding':digest(identity),'block':block['id'],'base':base,'model':name,'seconds':time.monotonic()-start,'rows':len(ii),'available_rows':int(available.sum()),'files':{p:s0.sha256(path/p) for p in ['fit.json','predictions.parquet','threshold_predictions.parquet']}})


def run(E,root,out,status):
    identity=validate(E,root);reg=s0.read_json(E/'implementations/s6_v1/registration.json')
    if (out/'run.json').exists():s0.require(s0.read_json(out/'run.json')==identity,'Changed run identity; use new output')
    else:save(out/'run.json',identity)
    if (out/'PREDICTION_RELEASE.json').exists():
        release=verify_record_file(out/'PREDICTION_RELEASE.json')
        for rel,h in release['files'].items():s0.require(s0.sha256(out/rel)==h,'Frozen prediction release changed')
        status('PREDICTIONS_FROZEN','Existing release verified');return
    ctx=Context(E,E/'implementations/s5_v1');status('CERTIFYING_BASE_LINEAGE')
    if (out/'BASE_REUSE_CERTIFICATE.json').exists():
        cert=verify_record_file(out/'BASE_REUSE_CERTIFICATE.json');s0.require(cert['binding']==digest(identity),'Certificate binding mismatch')
        for rel,h in cert['source_files'].items():s0.require(s0.sha256(E/rel)==h,'Certificate source changed')
    else:
        c=certificate(ctx,reg);sources=dict(ctx.authorities)
        seen=set()
        for row in c['fit_lineage_units']:
            sources[row['path']+'/UNIT.json']=row['unit_sha256']
            if row['training_metadata_sha256'] not in seen:
                sources[row['path']+'/training_metadata.json']=row['training_metadata_sha256'];seen.add(row['training_metadata_sha256'])
            if '/outer/' in row['path']:
                u=s0.read_json(E/row['path']/'UNIT.json')
                for rel,h in u['files'].items():sources[row['path']+'/'+rel]=h
        seal(out/'BASE_REUSE_CERTIFICATE.json',{**c,'binding':digest(identity),'source_files':sources})
    status('LOADING_ISSUANCE_PREDICTORS');data=load(ctx,reg);save(out/'INPUTS.json',data['input_hashes'])
    total=16;completed=0;durations=[]
    for b in reg['historical_blocks']:
        for base in reg['base_models']:
            for name in ['NATIVE','R0','R1','R2']:
                status('FITTING_AND_FREEZING',{'unit':f'{b["id"]}/{base}/{name}','completed':completed,'total':total,'eta_seconds':None if not durations else float(np.mean(durations)*(total-completed))})
                r=unit(E,out,data,ctx,reg,b,base,name,identity);completed+=1;durations.append(r['seconds'])
                if (out/'PAUSE_REQUESTED').exists():status('PAUSED','Remove PAUSE_REQUESTED to resume');return
    s0.require(validate(E,root)==identity,'Implementation changed during run')
    files={'run.json':s0.sha256(out/'run.json'),'BASE_REUSE_CERTIFICATE.json':s0.sha256(out/'BASE_REUSE_CERTIFICATE.json'),'INPUTS.json':s0.sha256(out/'INPUTS.json')}
    for p in sorted((out/'units').rglob('*')):
        if p.is_file():files[p.relative_to(out).as_posix()]=s0.sha256(p)
    seal(out/'PREDICTION_RELEASE.json',{'status':'FROZEN','binding':digest(identity),'files':files,'learned_fits':12,'native_reference_units':4,'historical_not_blind':True,'assessment_comparative_scores_computed':False,'prospective_active':False})
    status('PREDICTIONS_FROZEN','12 registered fits and four native references; scoring is a separate command')
