from pathlib import Path
from datetime import date,timedelta,datetime,timezone
from collections import Counter
import hashlib,json,os,resource,signal,time
import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
from scipy.interpolate import BSpline
import s0
from r14_s1.scoring import score_rows,weighted_quantile
from r14_s1.probability import summarize_pmf,round_half_away
from inputs import Context,MODELS,PRIMARY,save,seal,digest,verify_record_file
from core import block_weights,summarize,reliability,selective,regime_labels,day_sum,interval


def audit_tuning(ctx):
    """Timing audit; do not rewrite models. Excluding unavailable days is a sensitivity."""
    candidates=s0.read_json(ctx.E/'implementations/s3_v1/candidates.json');records=[]
    for fold in ctx.contract['folds']['outer']:
        oid=fold['outer_fold_id'];cut=date.fromisoformat(fold['assessment_start'])-timedelta(days=2)
        for model in MODELS:
            baseline=model.startswith('B0_');sel=s0.read_json(ctx.base/f'{oid}_{model}_selection.json' if baseline else ctx.run/f'selections/{oid}_{model}.json')
            if not baseline:
                cs=[c for c in candidates if c['model_id']==model];losses={c['candidate_id']:{} for c in cs};removed=set()
                for block in sel['blocks']:
                    scores=s0.read_json(ctx.run/'inner'/block/'SCORES.json')
                    for cid,values in scores['losses'].items():
                        removed.update(d for d in values if d>str(cut));losses[cid].update({d:v for d,v in values.items() if d<=str(cut)})
                means={cid:np.mean(list(v.values())) for cid,v in losses.items() if cid not in sel['invalid_candidates']}
                order=('seasonal_half_width_days','neighbors','bandwidth_multiplier','kernel_sigma_f') if model=='ANEN' else ('lambda_mu','lambda_scale')
                tied=[c for c in cs if c['candidate_id'] in means and means[c['candidate_id']]<=min(means.values())+1e-10];winner=max(tied,key=lambda c:tuple(c['parameters'][k] for k in order))
            else:
                cs=[c for c in s0.read_json(ctx.E/'config/candidates.json')['candidates'] if c['model_id']==model];means=dict(sel['inner_nll']);removed=set();n=sel['tuning_days'];sums={cid:v*n for cid,v in means.items()}
                for spec in ctx.contract['folds']['inner']:
                    iid=spec['inner_fold_id'];sp=ctx.base/f'{oid}_{model}_{iid}_support.json'
                    if not sp.exists() or not s0.read_json(sp)['summary']['included']:continue
                    late=[date.fromisoformat(spec['assessment_start'])+timedelta(days=i) for i in range((date.fromisoformat(spec['assessment_end'])-date.fromisoformat(spec['assessment_start'])).days+1) if date.fromisoformat(spec['assessment_start'])+timedelta(days=i)>cut]
                    if not late:continue
                    # The offending date is development-only but belongs to the nominal outer TRAIN set.
                    t=ctx.loader.supplement['truth_accessor']
                    from r14_s1.data import read_dates
                    auth=read_dates(ctx.loader._input(t['catalog']),t['catalog_authorization_columns'],late).to_pylist()
                    s0.require(all(a['truth_group']=='development' and a['label_available_for_supervised_use'] and a['source_artifact_path']==t['source_path'] and a['source_artifact_sha256']==t['source_sha256'] for a in auth),'Tuning audit truth authorization')
                    vals=read_dates(ctx.loader._input(t['source_path']),['target_date','y_audited_f'],late).to_pylist();yday={r['target_date']:r['y_audited_f'] for r in vals}
                    for c in cs:
                        unit=ctx.base/'units'/f'{oid}_{iid}_{c["candidate_id"]}';u=verify_record_file(unit/'unit.json',ctx.brelease['units'][str(unit.relative_to(ctx.base))]);m=verify_record_file(unit/'forecast/manifest.json',u['forecast_manifest_sha256'])
                        s0.require(s0.sha256(unit/'forecast/predictions.parquet')==m['predictions_sha256'],'Baseline audit prediction changed')
                        rows=read_dates(unit/'forecast/predictions.parquet',['target_date','status','probabilities','diagnostics_json'],late).to_pylist()
                        for d in late:
                            rs=[r for r in rows if r['target_date']==d and r['status']=='AVAILABLE'];s0.require(len(rs)>0,'Missing late tuning day')
                            # Frozen minimum seasonal width defines family common support.
                            # Here both width=45 and wider candidates have complete support on this year-end day.
                            if c['parameters']['seasonal_half_width_days']==45:s0.require(all(json.loads(r['diagnostics_json'])['pool_days']>=40 for r in rs),'Invalid baseline common support')
                            s0.require(len(rs)==len([r for r in rows if r['target_date']==d]),'Audit requires full availability on excluded day')
                            p=np.maximum(np.array([r['probabilities'] for r in rs]),1e-6);p/=p.sum(axis=1,keepdims=True);loss=float((-np.log(p[:,yday[d]+40])).mean());sums[c['candidate_id']]-=loss;removed.add(str(d))
                means={cid:value/(n-len(removed)) for cid,value in sums.items()};tied=[c for c in cs if means[c['candidate_id']]<=min(means.values())+1e-10];winner=max(tied,key=lambda c:(c['parameters']['seasonal_half_width_days'],c['parameters']['kernel_sigma_f']))
            records.append({'outer':oid,'model':model,'declared_cutoff':str(cut),'late_tuning_dates':sorted(removed),'selected_unchanged_after_exclusion':winner==sel['selected'],'original':sel['selected'],'sensitivity_selection':winner})
    return {'status':'TIMING_NONCONFORMANCE' if any(r['late_tuning_dates'] for r in records) else 'PASS','records':records,
            'scope':'Historical diagnostics; no frozen selection or prediction modified. Training fits enforce the lag, but tuning included one too-recent outcome per vintage. Correct workflow before future fits.'}


def score_model(ctx,model,meta=None):
    chunks=[];records=[];diagnostics=[];paths={}
    for f in ctx.contract['folds']['outer']:
        rows,unit=ctx.outer(f['outer_fold_id'],model);paths[f['outer_fold_id']]=unit
        records+=rows
    days=sorted({r['target_date'] for r in records});truth=ctx.truth(days);ids=[r['issue_state_id'] for r in records]
    if meta is not None:s0.require(ids==meta['ids'],'Model support/order differs')
    mapping={d:i for i,d in enumerate(days)};di=np.array([mapping[r['target_date']] for r in records]);y=np.array([truth[r['target_date']] for r in records]);p=np.array([r['probabilities'] for r in records]);point=np.array([r['point_f'] for r in records]);raw=np.array([r['baseline_center_f'] for r in records])
    scores=score_rows(p,y,ids,ctx.sc,point=raw if model.startswith('B0_') else point);summary=summarize_pmf(p)
    scores['raw_absolute_error']=np.abs(raw-y);scores['raw_squared_error']=(raw-y)**2;scores['raw_bias']=raw-y;scores['raw_integer_hit']=(round_half_away(raw)==y).astype(float)
    scores['continuous_location_absolute_error']=np.abs(point-y);scores['continuous_location_bias']=point-y
    
    for t in [3,5,10]:
        err=summary['mean']-y;scores[f'mean_ae_ge_{t}']=(np.abs(err)>=t).astype(float);scores[f'mean_warm_ge_{t}']=(err>=t).astype(float);scores[f'mean_cold_ge_{t}']=(err<=-t).astype(float)
    scores['median_signed_error']=summary['median']-y;scores['mode_signed_error']=summary['mode']-y
    scores['adjacent_js']=np.zeros(len(y));scores['absolute_mean_revision']=np.zeros(len(y));scores['absolute_mode_revision']=np.zeros(len(y));scores['adjacent_mae_gain']=np.zeros(len(y));scores['adjacent_hit_gain']=np.zeros(len(y))
    same=np.r_[False,di[1:]==di[:-1]];ii=np.where(same)[0]
    a=p[ii-1];b=p[ii];mid=(a+b)/2
    with np.errstate(divide='ignore',invalid='ignore'):
        js=.5*np.sum(np.where(a>0,a*np.log(np.divide(a,mid,out=np.ones_like(a),where=mid>0)),0)+np.where(b>0,b*np.log(np.divide(b,mid,out=np.ones_like(b),where=mid>0)),0),axis=1)
    scores['adjacent_js'][ii]=js;scores['absolute_mean_revision'][ii]=np.abs(summary['mean'][ii]-summary['mean'][ii-1]);scores['absolute_mode_revision'][ii]=np.abs(summary['mode'][ii]-summary['mode'][ii-1]);scores['adjacent_mae_gain'][ii]=scores['mae'][ii-1]-scores['mae'][ii];scores['adjacent_hit_gain'][ii]=scores['modal_integer_hit'][ii]-scores['modal_integer_hit'][ii-1]
    diag=[json.loads(r['diagnostics_json']) for r in records]
    auxiliary={k:summary[k] for k in ['mean','median','mode','lower_80','upper_80','width_80']};auxiliary.update(raw=raw,point=point)
    for key in ['kth_distance','effective_sample_size','out_of_range_fraction','scale_f','continuous_sd_f','pool_days','ood','out_of_range','distance_quantile']:
        auxiliary[key]=np.array([float(d[key]) if d.get(key) is not None else np.nan for d in diag])
    auxiliary['scale_near_bound_contract']=((auxiliary['scale_f']<=.26)|(auxiliary['scale_f']>=19.9)).astype(float)
    auxiliary['scale_near_bound_s3']=np.array([float(d.get('scale_near_bound',False)) for d in diag])
    base_meta={'ids':ids,'days':[str(d) for d in days],'di':di,'y':y,'minutes':np.array([r['local_minutes_since_0200'] for r in records]),'expected_counts':np.array([r['issue_count_for_target_day'] for r in records]),'outer':np.array([f'OUTER_0{r["target_date"].year-2022}' for r in records]),'adjacent':same}
    return scores,auxiliary,base_meta,paths


def build_slices(ctx,meta):
    n=len(meta['di']);rowdays=np.array(meta['days'])[meta['di']];minutes=meta['minutes'];out={'overall':np.full(n,'ALL',dtype='<U12'),'outer':meta['outer'],'year':np.array([d[:4] for d in rowdays]),'month':np.array([d[5:7] for d in rowdays]),'exact_issue':np.array([f'{2+m//60:02d}:{m%60:02d}' for m in minutes]),'source_era':np.full(n,'UNKNOWN',dtype='<U12')}
    out['season']=np.array([next(s for s,months in ctx.features['season_months'].items() if int(d[5:7]) in months) for d in rowdays]);out['issue_band']=np.where(minutes<240,'02–06',np.where(minutes<480,'06–10',np.where(minutes<660,'10–13','13–16')));out['season_x_issue_band']=np.char.add(np.char.add(out['season'],'/'),out['issue_band'])
    rules={};forecast=np.zeros(n);cyclemeta={};regcols=ctx.features['regime_definitions']
    for rd in regcols:out['weather/'+rd['id']]=np.full(n,'MISSING',dtype='<U12')
    for name in ['hourly_cycle_age','subhourly_cycle_age','cycle_transition','hourly_transition','subhourly_transition']:out[name]=np.full(n,'MISSING',dtype='<U24')
    for fold in ctx.contract['folds']['outer']:
        oid=fold['outer_fold_id'];idx=np.where(meta['outer']==oid)[0];train=ctx.features_batch(oid,'TRAIN');query=ctx.features_batch(oid,'ASSESS')
        s0.require([r['issue_state_id'] for r in query.metadata]==[meta['ids'][i] for i in idx],'Regime feature key mismatch')
        td=sorted(set(train.dates));tdi=np.array([td.index(d) for d in train.dates]);tm=np.array([r['local_minutes_since_0200'] for r in train.metadata]);qm=minutes[idx]
        for rd in regcols:
            j=train.columns.index(rd['column']);labels,thresholds=regime_labels(query.X[:,j],qm,train.X[:,j],tm,tdi,rd['method']);out['weather/'+rd['id']][idx]=labels;rules[oid+'/'+rd['id']]=thresholds
        forecast[idx]=(query.X[:,query.columns.index('q05_local_retained_max')]-273.15)*1.8+32
        changes=[]
        for short,prod in [('hourly','wrfsfcf'),('subhourly','wrfsubhf')]:
            vals=query.X[:,query.columns.index('clock_'+prod+'_cycle_age_minutes')];edges=ctx.features['cycle_age_bin_edges_minutes'];out[short+'_cycle_age'][idx]=np.array([f'[{edges[j]},{edges[j+1]})' if np.isfinite(x) and (j:=np.searchsorted(edges,x,side='right')-1)>=0 and j<len(edges)-1 else 'MISSING' for x in vals])
            cy=[m[prod+'_cycle_init_utc'] for m in query.metadata];first=np.r_[True,np.array(query.dates)[1:]!=np.array(query.dates)[:-1]];changed=np.r_[False,np.array(cy[1:])!=np.array(cy[:-1])];out[short+'_transition'][idx]=np.where(first,'FIRST',np.where(changed,'NEW','SAME'));changes.append(changed)
        out['cycle_transition'][idx]=np.where(first,'FIRST',np.where(changes[0]|changes[1],'NEW','SAME'))
    edges=ctx.features['temperature_bin_edges_f']
    for name,values in [('forecast_temperature',forecast),('realized_temperature_EX_POST',meta['y'])]:
        out[name]=np.array([f'[{edges[j]},{edges[j+1]})' if (j:=np.searchsorted(edges,x,side='right')-1)>=0 and j<len(edges)-1 else 'OUTSIDE' for x in values])
    return out,rules


def confidence_arrays(scores,aux):
    out={'integer':(scores['max_integer_probability'],scores['modal_integer_hit'],scores['max_integer_probability']),
         'negative_entropy':(scores['max_integer_probability'],scores['modal_integer_hit'],-scores['entropy']),
         'negative_width80':(scores['max_integer_probability'],scores['modal_integer_hit'],-aux['width_80'])}
    for name in ['pair_even','pair_odd','five_degree']:out[name]=(scores['synthetic_'+name+'_max_probability'],scores['synthetic_'+name+'_modal_hit'],scores['synthetic_'+name+'_max_probability'])
    return out


def gam_effects(ctx,paths):
    results=[]
    for model in ['GAM_LS_NORMAL','GAM_LOCATION_NORMAL','GAM_LS_T5']:
        for oid,unit in paths[model].items():
            manifest=verify_record_file(unit/'UNIT.json');p=unit/'fit_state.json';s0.require(s0.sha256(p)==manifest['files']['fit_state.json'],'Changed GAM state')
            state=s0.read_json(p);split=1+sum(state['location']['keep']);theta=np.array(state['theta'])
            for component,coef in [('location',theta[:split]),('scale_eta',theta[split:])]:
                design=state['location' if component=='location' else 'scale'];mean=np.array(design['mean']);rms=np.array(design['rms']);keep=np.array(design['keep'],bool);full=np.zeros(len(keep));full[keep]=coef[1:];offset=0
                for b in design['blocks']:
                    x=np.linspace(b['lo'],b['hi'],101)
                    raw=BSpline.design_matrix(x,b['knots'],3).toarray()[:,:-1] if b['kind']=='spline' else x[:,None]
                    width=raw.shape[1];v=((raw-mean[offset:offset+width])/rms[offset:offset+width])@full[offset:offset+width];offset+=width
                    results.append({'model':model,'outer':oid,'component':component,'feature':b['name'],'x':x.tolist(),'effect':v.tolist(),'range':[b['lo'],b['hi']],'uncertainty':'No fitted coefficient covariance or refit bootstrap available; curves are point estimates, not causal effects.'})
                if not design['constant']:
                    x=np.linspace(0,365,366);angle=x*2*np.pi/366;raw=np.column_stack([v for k in range(1,5) for v in [np.sin(k*angle),np.cos(k*angle)]])
                    v=((raw-mean[offset:])/rms[offset:])@full[offset:];results.append({'model':model,'outer':oid,'component':component,'feature':'season_angle_day_index','x':x.tolist(),'effect':v.tolist(),'range':[0,365],'uncertainty':'Point estimate; others held fixed. Scale effects are additive eta, not degrees F.'})
    return results


def main(ctx,out,status):
    started=time.monotonic();status('AUDITING_TIMING');timing=audit_tuning(ctx);save(out/'timing_audit.json',timing)
    meta=None;data={};aux={};paths={}
    for model in MODELS:
        status('SCORING_FROZEN_OUTER',model);data[model],aux[model],current,paths[model]=score_model(ctx,model,meta)
        if meta is None:meta=current
        pq.write_table(pa.table({**{'issue_state_id':meta['ids']},**data[model]}),out/(model+'_row_scores.parquet'))
    fold_issue={}
    for model in MODELS:
        fold_issue[model]={}
        for oid in sorted(set(meta['outer'])):
            fold_issue[model][oid]={}
            for minute in sorted(set(meta['minutes'])):
                mk=(meta['outer']==oid)&(meta['minutes']==minute);v=data[model];fold_issue[model][oid][f'{2+minute//60:02d}:{minute%60:02d}']={'days':int(mk.sum()),'rows':int(mk.sum()),'mae':float(v['mae'][mk].mean()),'negative_log_score':float(v['negative_log_score'][mk].mean()),'modal_integer_hit':float(v['modal_integer_hit'][mk].mean()),'calibration_gap':float((v['modal_integer_hit'][mk]-v['max_integer_probability'][mk]).mean()),'sparse':int(mk.sum())<60}
    save(out/'fold_issue.json',fold_issue)
    save(out/'population.json',{'days':meta['days'],'rows':len(meta['di']),'expected_rows_per_model':len(meta['di']),'all_models_available':True,'folds':ctx.contract['folds']['outer']})
    # Regression check against the user's already-inspected limited diagnostic.
    old=s0.read_json(ctx.E/'diagnostics/s4_model_review_v1/RESULTS.json')
    for m in MODELS:
        pooled=summarize(data[m],meta['di'],np.ones(len(meta['di']),bool))
        for k in ['mae','modal_integer_hit','negative_log_score','discrete_crps_f']:s0.require(abs(pooled['metrics'][k]-old['models'][m]['overall'][k])<1e-10,'Score regression: '+m+'/'+k)
    status('BUILDING_CALENDAR_BOOTSTRAPS');inf=ctx.contract['inference'];W=block_weights(meta['days'],ctx.contract['folds']['outer'],7,inf['replicates'],inf['seed']);W14=block_weights(meta['days'],ctx.contract['folds']['outer'],14,inf['replicates'],inf['seed'])
    status('TRAINING_ONLY_REGIME_THRESHOLDS');slices,regimes=build_slices(ctx,meta);save(out/'regime_thresholds.json',{'rules':regimes,'labels_used':False,'source':'eligible outer training predictors at the same issue minute'})
    n=len(meta['days']);di=meta['di'];expected=meta['expected_counts'];primary={}
    for block,B in [(7,W),(14,W14)]:
        results=[]
        for a,b in inf['primary_contrasts']:
            diff=data[a]['negative_log_score']-data[b]['negative_log_score'];cnt=np.bincount(di);daily=day_sum(diff,di,n)/cnt;draws=(B@daily)/B.sum(axis=1)
            results.append({'model':a,'reference':b,'difference':float(daily.mean()),'familywise_interval':interval(draws,(.005,.995)),'unadjusted_interval':interval(draws),'days':n,'checkpoints':len(di)})
        primary[str(block)]=results
    save(out/'paired_inference.json',{'definition':'model minus reference NLL; negative favors model','method':inf,'results':primary,'timing_audit_status':timing['status'],'promotion_allowed':False})
    status('INNER_CONFIDENCE_THRESHOLDS');thresholds={};inner={};support_labels={}
    for model in MODELS:
        support_labels[model]={}
        for f in ctx.contract['folds']['outer']:
            oid=f['outer_fold_id'];values=ctx.selected_inner(oid,model);inner[(oid,model)]=values
            for rank,x in values['ranks'].items():
                thresholds[oid+'/'+model+'/'+rank]={str(c):None if c==1 else weighted_quantile(x,values['weights'],1-c) for c in ctx.contract['selection']['coverages']}
            if model=='ANEN':
                idx=np.where(meta['outer']==oid)[0]
                for name in ['kth_distance','effective_sample_size']:
                    key='analog_'+name+'_quartile';support_labels[model].setdefault(key,np.full(len(di),'MISSING',dtype='<U12'))
                    train=np.array([d.get(name,np.nan) for d in values['diagnostics']]);rules={}
                    for minute in np.unique(meta['minutes'][idx]):
                        mask=(values['minutes']==minute)&np.isfinite(train);q=[weighted_quantile(train[mask],values['weights'][mask],p) for p in [.25,.5,.75]] if mask.any() else []
                        if q:
                            ii=idx[meta['minutes'][idx]==minute];v=aux[model][name][ii];support_labels[model][key][ii]=np.array(['MISSING' if not np.isfinite(x) else f'Q{np.searchsorted(q,x,side="left")+1}' for x in v]);rules[str(minute)]=q
                    regimes[oid+'/'+key]=rules
        support_labels[model]['out_of_range']=np.where(np.isfinite(aux[model]['out_of_range_fraction']),np.where(aux[model]['out_of_range_fraction']>0,'OUTSIDE','WITHIN'),np.where(np.isfinite(aux[model]['out_of_range']),np.where(aux[model]['out_of_range']>0,'OUTSIDE','WITHIN'),'NOT_RECORDED'))
    save(out/'confidence_thresholds.json',{'source':'selected candidate forecasts on included common-support inner blocks, no outer probabilities or outcomes','thresholds':thresholds,'ties':'all admitted; None means -infinity for 100% target','qualification':'These inner forecasts also selected base settings. They are tuning evidence, not independent reliability-model training. Existing base selections have the disclosed one-day timing nonconformance.'})
    save(out/'regime_thresholds.json',{'rules':regimes,'labels_used':False,'analog_source':'selected inner forecast diagnostics, exact issue','physical_source':'eligible outer training predictors'})
    scorecards={};calibration={};histograms={};selection={};cases={};operations={}
    allmask=np.ones(len(di),bool)
    for model in MODELS:
        status('SCORECARD_AND_UNCERTAINTY',model);scorecards[model]={};calibration[model]={};histograms[model]={};selection[model]=[]
        model_slices={**slices,**support_labels[model]}
        for family,labels in model_slices.items():
            scorecards[model][family]={}
            for label in sorted(set(labels) | ({'MISSING','LOW','MIDDLE','HIGH'} if family.startswith('weather/') and any(r['id']==family.split('/',1)[1] and r['method']!='positive_vs_nonpositive' for r in ctx.features['regime_definitions']) else set())):
                mask=labels==label
                if family in ['cycle_transition','hourly_transition','subhourly_transition'] and label=='FIRST': pass
                scorecards[model][family][label]=summarize(data[model],di,mask,W)
        for family in ['overall','outer','season','issue_band']:
            for label in sorted(set(slices[family])):
                mask=slices[family]==label;events={'integer':(data[model]['max_integer_probability'],data[model]['modal_integer_hit'])}
                for name in ctx.sc['partitions']:events[name]=(data[model]['synthetic_'+name+'_max_probability'],data[model]['synthetic_'+name+'_modal_hit'])
                for t in ctx.sc['thresholds_f']:events[f'threshold_{t}']=(data[model][f'threshold_{t}_probability'],data[model][f'threshold_{t}_event'])
                calibration[model][family+'/'+label]={name:reliability(p,y,di,mask,W if family in ['overall','outer'] else None) for name,(p,y) in events.items()}
        for family in ['overall','season','issue_band']:
            for label in sorted(set(slices[family])):
                mask=slices[family]==label;counts=day_sum(mask.astype(float),di,n);w=np.divide(mask,counts[di],out=np.zeros(len(di)),where=counts[di]>0);w/=w.sum()
                h,edges=np.histogram(data[model]['randomized_pit'],bins=np.linspace(0,1,11),weights=w)
                error=data[model]['median_signed_error'];eh,ee=np.histogram(np.clip(error,-15,15),bins=np.arange(-15.5,16.5),weights=w)
                histograms[model][family+'/'+label]={'pit':h.tolist(),'pit_edges':edges.tolist(),'signed_error':eh.tolist(),'signed_edges':ee.tolist(),'error_tail_clipping':'<=-15 and >=15 accumulate at ends'}
        ranks=confidence_arrays(data[model],aux[model])
        for ranking,(prob,event,rank) in ranks.items():
            event_scores={**data[model],'event_hit':event};base={m:{**data[m],'event_hit':confidence_arrays(data[m],aux[m])[ranking][1]} for m in ['B0_H','B0_Q']}
            for target in ctx.contract['selection']['coverages']:
                thresholds_array=np.array([(-np.inf if target==1 else thresholds[oid+'/'+model+'/'+ranking][str(target)]) for oid in meta['outer']])
                admitted=rank>=thresholds_array
                # Pooled selection uses each vintage's own frozen threshold, never a pooled outer quantile.
                for family in ['overall','outer','season','issue_band']:
                    for label in sorted(set(slices[family])):
                        mask=slices[family]==label
                        ss=selective(event_scores,prob,np.where(admitted,1.,0.),di,expected,mask,.5,W,base)
                        ss.update(ranking=ranking,target_coverage=target,slice=family+'/'+label)
                        # Day-count vectors use the explicit population.json date order.
                        selection[model].append(ss)
        selected_cases=[];daily=day_sum(data[model]['mae'],di,n)/np.bincount(di)
        selected_cases += [('largest_error',meta['days'][i]) for i in sorted(range(n),key=lambda i:(-daily[i],meta['days'][i]))[:5]]
        for kind,hit in [('hit',1),('miss',0)]:
            eligible=[d for d,i in zip(meta['days'],range(n)) if any((di==i)&(meta['minutes']==480)&(data[model]['modal_integer_hit']==hit))]
            chosen=sorted(eligible,key=lambda d:hashlib.sha256(f'3750925|{model}|{d}'.encode()).hexdigest())[:5];selected_cases += [(kind,d) for d in chosen]
        cases[model]=[]
        for kind,d in selected_cases:
            idx=np.where(np.array(meta['days'])[di]==d)[0];cases[model].append({'kind':kind,'day':d,'truth':int(meta['y'][idx[0]]),'minutes':meta['minutes'][idx].tolist(),'mean':aux[model]['mean'][idx].tolist(),'mode':aux[model]['mode'][idx].tolist(),'lower80':aux[model]['lower_80'][idx].tolist(),'upper80':aux[model]['upper_80'][idx].tolist(),'raw':aux[model]['raw'][idx].tolist(),'probability':data[model]['max_integer_probability'][idx].tolist(),'hit':data[model]['modal_integer_hit'][idx].tolist(),'cycle_transition':slices['cycle_transition'][idx].tolist()})
        operations[model]={'outer_units':{},'fit_vs_predict_time':'Only combined unit wall time was recorded; separate timings unavailable.','historical_peak_memory':'NOT_RECORDED','fallback':'NONE','abstentions':0}
        for oid,unit in paths[model].items():
            rec=s0.read_json(unit/('unit.json' if model.startswith('B0_') else 'UNIT.json'));operations[model]['outer_units'][oid]={'combined_seconds':rec['seconds'],'fit_state':'frozen','scale_near_bounds_contract_fraction':float(np.mean(aux[model]['scale_near_bound_contract'][meta['outer']==oid])) if model.startswith('GAM') else None}
        intraday={}
        for label in ['ALL','NEW','SAME']:
            mk=meta['adjacent'] & (np.ones(len(di),bool) if label=='ALL' else slices['cycle_transition']==label)
            ds={k:data[model][k] for k in ['mae','mean_squared_error']}
            ds.update({k:data[model][v] for k,v in [('js','adjacent_js'),('mean_revision','absolute_mean_revision'),('mode_revision','absolute_mode_revision'),('mae_gain','adjacent_mae_gain'),('hit_gain','adjacent_hit_gain')]})
            intraday[label]=summarize(ds,di,mk)
        save(out/(model+'_intraday.json'),{'summaries':intraday,'interpretation':'Adjacent available issue comparisons; first checkpoint excluded. NEW/SAME associations are not causal information-value estimates.'})
        save(out/'scorecards.json',scorecards);save(out/'calibration.json',calibration);save(out/'histograms.json',histograms);save(out/'selection.json',selection);save(out/'cases.json',cases);save(out/'operations.json',operations)
    status('EXTRACTING_FROZEN_GAM_EFFECTS');save(out/'gam_effects.json',gam_effects(ctx,paths))
    save(out/'provenance.json',{'input_hashes':ctx.authorities,'truth_sha256':ctx.loader.supplement['truth_accessor']['source_sha256'],'reserved_or_tail_labels_read':False,'model_fits_performed':False,'gate_fits_performed':False,'historical_evidence':'Previously inspected development outcomes; no fresh-blind claim','memory_bytes_this_process':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,'analysis_seconds':time.monotonic()-started,'prior_summary_reproduced':True})
    return {'timing_audit':timing['status'],'models':len(MODELS),'days':n,'rows_per_model':len(di)}
