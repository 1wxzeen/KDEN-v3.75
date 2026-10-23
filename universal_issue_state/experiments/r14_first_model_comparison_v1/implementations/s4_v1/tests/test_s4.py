from pathlib import Path
from datetime import date, timedelta
from dataclasses import replace
from unittest.mock import patch
import importlib.util, json, os, sys, tempfile, unittest
from zoneinfo import ZoneInfo
import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
ROOT = Path(__file__).resolve().parents[1]
E = Path(os.environ['R14_EXPERIMENT_ROOT']); S3 = E/'implementations/s3_v1'
sys.path[:0] = [str(ROOT), str(E/'src'), str(S3)]
import engine, s0
from r14_s1.data import FeatureBatch, legal_issue_times
from r14_s3.anen import Analog
from r14_s3.runtime import load_fit
CFG = s0.read_json(S3/'config.json')


def fixture(model='ANEN', n=180, start=date(2021,1,1), split='TRAIN', inner='INNER_01', outer='OUTER_01'):
    rng=np.random.default_rng(33); days=[start+timedelta(days=i) for i in range(n)]
    columns=list(CFG['features'])+[CFG['center']]+CFG['clocks']; X=rng.normal(size=(n,len(columns)))
    def put(name, value): X[:,columns.index(name)]=value
    put(CFG['center'], 295+rng.normal(0,2,n))
    put('clock_issue_minutes_since_0200',60); put('clock_local_dst_flag',0)
    put('clock_target_doy_sin',np.sin(np.arange(n)*2*np.pi/366));put('clock_target_doy_cos',np.cos(np.arange(n)*2*np.pi/366))
    for name in ['clock_wrfsfcf_cycle_age_minutes','clock_wrfsubhf_cycle_age_minutes']: put(name,120)
    meta=tuple({'target_date':d,'local_minutes_since_0200':60,'issue_state_id':str(d),'issue_time_utc':next(t for t in legal_issue_times(d) if t.astimezone(ZoneInfo('America/Denver')).hour==3 and t.minute==0),
                'issue_count_for_target_day':len(legal_issue_times(d)),'statistical_group_id':'KDEN_DAY_'+str(d)} for d in days)
    batch=FeatureBatch(model,tuple(columns),X,meta,np.ones(n,dtype=bool),tuple(() for _ in days),{'fixture':'0'*64},outer,inner,split)
    y=np.rint((X[:,columns.index(CFG['center'])]-273.15)*1.8+34+rng.normal(size=n)).astype(int)
    return batch,y


def candidate(cid='a', model='ANEN', **kwargs):
    params=dict(seasonal_half_width_days=90,neighbors=15,bandwidth_multiplier=1.,kernel_sigma_f=1.25) if model=='ANEN' else dict(lambda_mu=.01,lambda_scale=.1)
    params.update(kwargs); return {'candidate_id':cid,'model_id':model,'parameters':params}


class DummyLoader:
    s3=CFG
    def input_hashes(self): return {'fixture':'0'*64}


class SelectionTests(unittest.TestCase):
    def test_equal_day_not_equal_block(self):
        a,b=candidate('a'),candidate('b',neighbors=20)
        selected,means=engine.choose([a,b],{'a':{'d1':0,'d2':0,'d3':6},'b':{'d1':3,'d2':3,'d3':1}}, {})
        self.assertEqual(selected,a);self.assertEqual(means['a'],2)
    def test_ties_and_invalid(self):
        a,b=candidate('a'),candidate('b',neighbors=20)
        scores={'a':{'d':2},'b':{'d':2+5e-11}}
        self.assertEqual(engine.choose([a,b],scores,{})[0],b)
        self.assertEqual(engine.choose([a,b],scores,{'b':'failed'})[0],a)
        self.assertIsNone(engine.choose([a,b],scores,{'a':'failed','b':'failed'})[0])
    def test_mismatched_support_fails(self):
        with self.assertRaises(s0.ContractError): engine.choose([candidate('a'),candidate('b')],{'a':{'d1':1},'b':{'d2':1}}, {})
    def test_gam_tie_order(self):
        a=candidate('a','GAM_LS_NORMAL');b=candidate('b','GAM_LS_NORMAL',lambda_mu=1.)
        self.assertEqual(engine.choose([a,b],{'a':{'d':2},'b':{'d':2}}, {})[0],b)
    def test_common_support_matches_all_native_configs(self):
        train,y=fixture();query,_=fixture(n=200,start=date(2022,1,1),split='ASSESS')
        cs=[candidate('a',seasonal_half_width_days=45,neighbors=60),candidate('b')]
        fitted=Analog(train,y,CFG)
        masks=[np.array([r[4] is None for r in fitted.forecast(query,c['parameters'])]) for c in cs]
        np.testing.assert_equal(engine.common_support(train,query,cs,CFG),np.logical_and.reduce(masks))
    def test_missing_and_constant_features(self):
        train,_=fixture();query,_=fixture(n=2,start=date(2022,1,1),split='ASSESS')
        query=replace(query,available=np.array([False,True]))
        self.assertEqual(engine.common_support(train,query,[candidate()],CFG).tolist(),[False,True])
        for name in CFG['features']: train.X[:,train.columns.index(name)]=1
        self.assertFalse(engine.common_support(train,query,[candidate()],CFG).any())
    def test_empty_complete_training_support_excludes_gam(self):
        train,_=fixture('GAM_LS_NORMAL');query,_=fixture('GAM_LS_NORMAL',n=2,start=date(2022,1,1),split='ASSESS')
        train=replace(train,available=np.zeros(len(train.metadata),bool))
        self.assertFalse(engine.common_support(train,query,[candidate('g','GAM_LS_NORMAL')],CFG).any())

    def test_no_outer_label_access(self):
        query,_=fixture(n=2,start=date(2023,1,1),split='ASSESS',inner=None)
        with patch.object(engine,'read_dates',side_effect=AssertionError('truth touched')):
            with self.assertRaisesRegex(s0.ContractError,'Outer scoring forbidden'):
                engine.inner_labels(None,query,np.ones(2,bool),[],[],'0'*64)
    def test_incomplete_candidates_cannot_read_labels(self):
        query,_=fixture(n=2,start=date(2022,1,1),split='ASSESS')
        with patch.object(engine,'read_dates',side_effect=AssertionError('truth touched')):
            with self.assertRaisesRegex(s0.ContractError,'Unsealed candidate set'):
                engine.inner_labels(None,query,np.ones(2,bool),[],[candidate()],'0'*64)
    def test_floor_and_renormalization(self):
        P=np.zeros((2,161));P[:,80]=1
        losses=engine.day_losses(P,np.array([40,41]),[date(2022,1,1)]*2)
        expected=(-np.log(1/(1+160e-6))-np.log(1e-6/(1+160e-6)))/2
        self.assertAlmostEqual(next(iter(losses.values())),expected)


class UnitTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.train,self.y=fixture();self.query,_=fixture(n=3,start=date(2022,1,1),split='ASSESS')
    def tearDown(self): self.tmp.cleanup()
    def make(self, path=None, c=None, unsupported=None, query=None):
        return engine.make_unit(path or self.root/'unit', self.train,query or self.query,self.y,c or candidate(),CFG,S3,DummyLoader(),'a'*64,date(2021,12,30),unsupported=unsupported)
    def test_commit_resume_reload_and_tamper(self):
        result=self.make();self.assertEqual(result['status'],'PREDICTIONS_FROZEN')
        with patch.object(engine.runtime,'fit',side_effect=AssertionError('refit on resume')): self.assertEqual(result,self.make())
        restored=load_fit(self.root/'unit',CFG)
        expected=list(Analog(self.train,self.y,CFG).forecast(self.query,candidate()['parameters']))
        actual=list(restored.forecast(self.query,candidate()['parameters']))
        for a,b in zip(actual,expected): np.testing.assert_array_equal(a[2],b[2])
        with (self.root/'unit/fit_state.json').open('a') as f:f.write(' ')
        with self.assertRaisesRegex(s0.ContractError,'bytes changed'):self.make()
    def test_identity_drift_fails(self):
        self.make()
        with self.assertRaisesRegex(s0.ContractError,'another run'): engine.verify_unit(self.root/'unit','b'*64)
    def test_publication_failure_commits_nothing(self):
        with patch.object(engine,'publish_partition',side_effect=OSError('disk full')):
            with self.assertRaises(OSError): self.make()
        self.assertFalse((self.root/'unit').exists());self.assertEqual(list(self.root.glob('.uncommitted-*')),[])
    def test_solver_failure_is_sealed(self):
        exc=s0.ContractError('ALL_GAM_STARTS_FAILED');exc.starts=[{'accepted':False,'objective':float('inf'),'gradient_inf':float('nan')}]
        with patch.object(engine.runtime,'fit',side_effect=exc):result=self.make()
        self.assertEqual(result['status'],'INVALID_SOLVER');engine.verify_unit(self.root/'unit','a'*64)
        failure=s0.read_json(self.root/'unit/solver_failure.json');self.assertEqual(failure['starts'][0]['objective'],'Infinity');self.assertEqual(failure['starts'][0]['gradient_inf'],'NaN')
    def test_unexpected_error_not_scientific_failure(self):
        with patch.object(engine.runtime,'fit',side_effect=s0.ContractError('bug')):
            with self.assertRaisesRegex(s0.ContractError,'bug'):self.make()
        self.assertFalse((self.root/'unit').exists())
    def test_outer_failure_publishes_all_abstentions(self):
        query=replace(self.query,inner_fold_id=None)
        self.make(query=query,unsupported='NO_VALID_CONFIGURATION')
        rows=engine.aligned_rows(self.root/'unit',[m['issue_state_id'] for m in query.metadata],['probabilities','status','abstention_reason'])
        self.assertTrue(all(r['status']=='ABSTAIN' and r['probabilities'] is None for r in rows))
    def test_authorized_inner_accessor_and_full_registry(self):
        self.make();c=candidate();loader=DummyLoader();loader.experiment=self.root/'experiment'
        engine.write(loader.experiment/'implementations/s3_v1/candidates.json',[c])
        source=self.root/'truth.parquet';catalog=self.root/'catalog.parquet'
        pq.write_table(pa.Table.from_pylist([{'target_date':d,'y_audited_f':80+i} for i,d in enumerate(self.query.dates)]),source)
        cols=['target_date','truth_group','label_available_for_supervised_use','source_artifact_path','source_artifact_sha256']
        rows=[dict(zip(cols,[d,'development',True,str(source),s0.sha256(source)])) for d in self.query.dates]
        pq.write_table(pa.Table.from_pylist(rows),catalog)
        loader.supplement={'truth_accessor':{'catalog':str(catalog),'catalog_authorization_columns':cols,'source_path':str(source),'source_sha256':s0.sha256(source),'source_max_date':'2022-01-03'}}
        loader._input=lambda p:Path(p);loader.fold_dates=lambda *args:self.query.dates
        y=engine.inner_labels(loader,self.query,np.array([True,False,True]),[self.root/'unit'],[c],'a'*64)
        np.testing.assert_array_equal(y,[80,82])
        engine.write(loader.experiment/'implementations/s3_v1/candidates.json',[c,candidate('b')])
        with self.assertRaisesRegex(s0.ContractError,'complete registered candidate family'):engine.inner_labels(loader,self.query,np.ones(3,bool),[self.root/'unit'],[c],'a'*64)
        engine.write(loader.experiment/'implementations/s3_v1/candidates.json',[c])
        rows[0]['truth_group']='reserved';pq.write_table(pa.Table.from_pylist(rows),catalog)
        with self.assertRaisesRegex(s0.ContractError,'Unauthorized inner truth'):engine.inner_labels(loader,self.query,np.ones(3,bool),[self.root/'unit'],[c],'a'*64)

    def test_alignment_by_id_not_row_order(self):
        self.make();ids=[m['issue_state_id'] for m in self.query.metadata][::-1]
        self.assertEqual([r['issue_state_id'] for r in engine.aligned_rows(self.root/'unit',ids,['status'])],ids)
        with self.assertRaises(s0.ContractError):engine.aligned_rows(self.root/'unit',ids[:-1],['status'])


CONTRACT={'folds':{'outer':[
    {'outer_fold_id':'OUTER_01','train_end':'2022-12-31','assessment_start':'2023-01-01'},
    {'outer_fold_id':'OUTER_02','train_end':'2023-12-31','assessment_start':'2024-01-01'}],
    'inner':[{'inner_fold_id':'INNER_01','assessment_start':'2022-01-01','assessment_end':'2022-03-01'},
             {'inner_fold_id':'INNER_02','assessment_start':'2022-03-02','assessment_end':'2022-04-30'}]}}

class WorkflowLoader(DummyLoader):
    contract=CONTRACT
    def __init__(self,*args):pass
    def load_features(self,model,outer,split='TRAIN',inner=None):
        start=date(2021,1,1) if split=='TRAIN' else (date(2022,1,1) if inner=='INNER_01' else date(2022,3,2) if inner else date(2023 if outer=='OUTER_01' else 2024,1,1))
        return fixture(model,n=180 if split=='TRAIN' else 60 if inner else 3,start=start,split=split,inner=inner,outer=outer)[0]
    def training_labels(self,batch):return np.rint((batch.X[:,batch.columns.index(CFG['center'])]-273.15)*1.8+34).astype(int)
    def fold_dates(self,outer,split,inner):return self.load_features('ANEN',outer,split,inner).dates

class WorkflowTests(unittest.TestCase):
    def test_pause_resume_and_unique_inner_reuse(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);experiment=root/'experiment';s3=experiment/'implementations/s3_v1';s3.mkdir(parents=True)
            for name in ['config.json','RELEASE.json']:shutil_copy(S3/name,s3/name)
            cs=[candidate('a'),candidate('b',neighbors=20)]
            engine.write(s3/'candidates.json',cs)
            seen=[]
            def labels(loader,q,mask,paths,candidates,sha):
                self.assertIsNotNone(q.inner_fold_id);self.assertEqual(len(paths),2)
                for p,c in zip(paths,candidates):engine.verify_unit(p,sha,c)
                seen.append(q.inner_fold_id)
                return np.rint((q.X[:,q.columns.index(CFG['center'])]-273.15)*1.8+34).astype(int)[mask]
            with patch.object(engine,'Loader',WorkflowLoader),patch.object(engine,'binding',return_value={'fixture':1}),patch.object(engine,'MODELS',['ANEN']),patch.object(engine,'inner_labels',side_effect=labels),patch.object(engine,'finalize',return_value={'unsupported_models':[]}):
                run=root/'run'
                result=engine.run(ROOT,experiment,root,run,max_new_units=1)
                self.assertEqual(result['state'],'PAUSED');self.assertEqual(seen,[])
                checkpoint=next(run.glob('inner/*/*/UNIT.json'));before=checkpoint.read_bytes()
                result=engine.run(ROOT,experiment,root,run)
                self.assertEqual(result['state'],'COMPLETE');self.assertEqual(result['completed_candidate_decisions'],6)
                self.assertEqual(seen,['INNER_01','INNER_02']);self.assertEqual(before,checkpoint.read_bytes())
                self.assertEqual(len(list(run.glob('inner/*/*/UNIT.json'))),4)
                self.assertEqual((run/'inner/INNER_01_ANEN/a/training.npz').stat().st_ino, (run/'inner/INNER_01_ANEN/b/training.npz').stat().st_ino)
                again=engine.run(ROOT,experiment,root,run)
                self.assertEqual(again['new_units_this_invocation'],0);self.assertEqual(len(seen),2)
    def test_release_common_support_and_expected_keys(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);run=root/'run';run.mkdir();identity={'fixture':1};sha=engine.digest(identity)
            models=['ANEN','GAM_LS_NORMAL'];baseline={}
            for outer in CONTRACT['folds']['outer']:
                oid=outer['outer_fold_id'];baseline[oid]={}
                for model in ['B0_H','B0_Q']+models:
                    train,y=fixture(model=model);query,_=fixture(model=model,n=3,start=date.fromisoformat(outer['assessment_start']),split='ASSESS',inner=None,outer=oid)
                    path=run/'outer'/f'{oid}_{model}'
                    if model in models:
                        engine.make_unit(path,train,query,y,candidate(model,model),CFG,S3,DummyLoader(),sha,date.fromisoformat(outer['assessment_start'])-timedelta(days=2))
                    else:
                        (path/'forecast').mkdir(parents=True)
                        pq.write_table(pa.Table.from_pylist([{'issue_state_id':m['issue_state_id'],'target_date':m['target_date'],'status':'AVAILABLE'} for m in query.metadata]),path/'forecast/predictions.parquet')
                        engine.write(path/'forecast/manifest.json',{'synthetic_test':True})
                        baseline[oid][model]=path
            with patch.object(engine,'MODELS',models),patch.object(engine,'binding',return_value=identity),patch.object(engine,'baseline_partitions',side_effect=lambda e,o:baseline[o]):
                release=engine.finalize(run,root,CONTRACT,sha,identity,ROOT,root)
                self.assertEqual(len(release['outer_partitions']),8)
                self.assertEqual(release['coverage']['OUTER_01']['primary_common']['available_rows'],3)
                self.assertFalse(release['outer_scores_computed'])
                path=baseline['OUTER_01']['B0_H']/'forecast/predictions.parquet'
                rows=pq.read_table(path).to_pylist();rows[0]['issue_state_id']='wrong';pq.write_table(pa.Table.from_pylist(rows),path)
                with self.assertRaisesRegex(s0.ContractError,'Forecast key mismatch'):engine.finalize(run,root,CONTRACT,sha,identity,ROOT,root)

    def test_unsupported_selection_under_two_blocks(self):
        with tempfile.TemporaryDirectory() as tmp:
            block=Path(tmp)/'b';engine.write(block/'SUPPORT.json',{'summary':{'included':False}})
            engine.seal(block/'SCORES.json',{'losses':{},'invalid':{}})
            selected=engine.select_outer('ANEN','OUTER_01',[candidate()],[block],'a'*64)
            self.assertEqual(selected['unsupported_reason'],'INSUFFICIENT_TUNING_SUPPORT')


def shutil_copy(src,dst): dst.write_bytes(src.read_bytes())
if __name__=='__main__':unittest.main()
