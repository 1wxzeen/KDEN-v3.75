from pathlib import Path
from datetime import date
import copy,json
import numpy as np
import pyarrow.parquet as pq
import s0
from inputs import Context,save,seal,verify_record_file,digest
from workflow import audit_tuning
from boundaries import assert_eligible,cutoff
from r14_s1.data import DevelopmentLoader
from r14_s1.probability import summarize_pmf
from model import design


def certificate(ctx,reg):
    # Recompute from frozen loss records, excluding unavailable dates before choosing a winner.
    audit=audit_tuning(ctx)
    if not all(x['selected_unchanged_after_exclusion'] for x in audit['records']):raise ValueError('REUSE_REJECTED: corrected selection differs; successor base fits required')
    units=[];metadata_cache={}
    for fold in ctx.contract['folds']['outer']:
        oid=fold['outer_fold_id'];start=fold['assessment_start']
        for model in reg['base_models']:
            sel=s0.read_json(ctx.run/'selections'/f'{oid}_{model}.json')
            candidates=[]
            for block,h in sel['blocks'].items():
                sp=ctx.run/'inner'/block/'SCORES.json';scores=verify_record_file(sp,h)
                if not scores.get('losses'):continue
                iid=block[:8];spec=next(x for x in ctx.contract['folds']['inner'] if x['inner_fold_id']==iid)
                support=s0.read_json(sp.parent/'SUPPORT.json')
                s0.require(digest(support)==scores['support_sha256'],'Score support changed')
                for cid,uh in scores['units'].items():
                    unit=sp.parent/cid;u=verify_record_file(unit/'UNIT.json');s0.require(u['record_sha256']==uh,'Score-unit binding changed')
                    if u.get('status')!='PREDICTIONS_FROZEN':continue
                    candidates.append((unit,u,spec['assessment_start'],iid))
            ref=ctx.release['outer_partitions'][oid+'/'+model];unit=(ctx.run/ref['path']).resolve();u=verify_record_file(unit/'UNIT.json');candidates.append((unit,u,start,None))
            for unit,u,boundary,iid in candidates:
                mp=unit/'training_metadata.json';h=u['files']['training_metadata.json']
                if h not in metadata_cache:
                    s0.require(s0.sha256(mp)==h,'Training metadata changed')
                    m=s0.read_json(mp);dates=sorted({x['target_date'] for x in m['rows']});assert_eligible(dates,boundary,*reg['evidence']['historical_allowed'])
                    allowed=set(str(d) for d in ctx.loader.fold_dates(oid,'TRAIN',iid));s0.require(set(dates)<=allowed,'Training metadata outside eligible fold')
                    metadata_cache[h]={'dates':dates,'max':max(dates),'rows':len(m['rows'])}
                else:assert_eligible(metadata_cache[h]['dates'],boundary,*reg['evidence']['historical_allowed'])
                if iid is None:
                    # Selected outer fit artifacts are verified once, not every discarded inner fit array.
                    for rel,fh in u['files'].items():s0.require(s0.sha256(unit/rel)==fh,'Selected outer fit changed: '+rel)
                    ident=s0.read_json(unit/'identity.json');s0.require(ident['parameters']==sel['selected']['parameters'],'Selection-fit settings mismatch')
                units.append({'path':str(unit.relative_to(ctx.E)),'unit_sha256':s0.sha256(unit/'UNIT.json'),'training_metadata_sha256':h,'training_max':metadata_cache[h]['max'],'cutoff':str(cutoff(boundary))})
    return {'status':'LAG_CORRECT_SELECTION_EQUIVALENCE_CERTIFIED','original_timing_nonconformance_preserved':True,'original_forecasts_regenerated':False,'historical_not_blind':True,'audit':audit,'fit_lineage_units':units,'verification_scope':'All referenced UNIT and score/support records; shared training metadata once per unique hash; selected primary outer fit artifacts and predictions. Not an exhaustive reread of every inner training array.'}


def load(ctx,reg,probe=False):
    names=[x['column'] for x in reg['weather_features']]+['clock_target_doy_sin','clock_target_doy_cos']
    loader=DevelopmentLoader(ctx.R,ctx.E);loader.features=copy.deepcopy(loader.features);loader.features['sets']['B0_Q']=names
    meta=[];parts=[];base={m:[] for m in ['ANEN','GAM_LS_NORMAL','B0_H','B0_Q']}
    for fold in ctx.contract['folds']['outer']:
        oid=fold['outer_fold_id'];dates=None
        if probe:
            if oid!='OUTER_01':continue
            eligible=loader.fold_dates(oid,'ASSESS');dates=[d for d in eligible if date(2023,1,1)<=d<=date(2023,6,29)][::1]
        b=loader.load_features('B0_Q',oid,'ASSESS',dates=dates);meta.extend(b.metadata);parts.append(b.X)
        for model in base:
            rows,_=ctx.outer(oid,model);lookup={r['issue_state_id']:r for r in rows};rs=[lookup[r['issue_state_id']] for r in b.metadata]
            for r in rs:
                s0.require(r['label_cutoff']==cutoff(fold['assessment_start']),'Wrong forecast cutoff')
                s0.require(r['training_end']<=cutoff(fold['assessment_start']),'Unavailable training label')
            probs=np.array([r['probabilities'] for r in rs]);s=summarize_pmf(probs)
            base[model].append({'native':s['max_integer_probability'],'integer':s['mode'],'median':s['median']})
    X=np.concatenate(parts);meta=list(meta);ids=[r['issue_state_id'] for r in meta]
    s0.require(len(ids)==len(set(ids)),'Duplicate CR1 issue ids')
    dates=np.array([str(r['target_date']) for r in meta]);minutes=np.array([r['local_minutes_since_0200'] for r in meta]);expected=np.array([r['issue_count_for_target_day'] for r in meta])
    weather={k:X[:,i] for i,k in enumerate(names)};designs={};common=np.ones(len(meta),bool)
    for model in base:base[model]={k:np.concatenate([x[k] for x in base[model]]) for k in ['native','integer','median']}
    for model in reg['base_models']:
        designs[model],valid=design(base[model]['native'],minutes,weather['clock_target_doy_sin'],weather['clock_target_doy_cos'],weather,reg);common &= valid
    return {'meta':meta,'ids':ids,'dates':dates,'minutes':minutes,'expected':expected,'base':base,'designs':designs,'common':common,'input_hashes':{**ctx.authorities,**loader.input_hashes()}}


def labels(ctx,data,mask,first_assessment,reg):
    days=sorted(set(data['dates'][mask]));assert_eligible(days,first_assessment,*reg['evidence']['historical_allowed'])
    truth=ctx.truth([date.fromisoformat(d) for d in days]);out=np.full(len(data['dates']),np.nan)
    for i in np.where(mask)[0]:out[i]=truth[date.fromisoformat(data['dates'][i])]
    return out
