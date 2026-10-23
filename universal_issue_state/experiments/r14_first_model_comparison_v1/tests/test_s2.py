from datetime import date,timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import sys,tempfile,unittest,json
import numpy as np
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
import s0
from r14_s1.data import legal_issue_times
from r14_s2.model import *
from r14_s2.workflow import create_unit,verify_unit,inner_labels


def batch(days,model='B0_H',split='TRAIN',center=70.,minutes=(0,15)):
    metadata=[]
    for day in days:
        for minute in minutes:
            utc=next(t for t in legal_issue_times(day) if t.astimezone(__import__('zoneinfo').ZoneInfo('America/Denver')).hour*60+t.astimezone(__import__('zoneinfo').ZoneInfo('America/Denver')).minute-120==minute)
            metadata.append(dict(target_date=day,local_minutes_since_0200=minute,issue_state_id=f'{day}:{minute}',statistical_group_id='KDEN_DAY_'+str(day),issue_time_utc=utc,issue_count_for_target_day=len(legal_issue_times(day))))
    return SimpleNamespace(model_id=model,split=split,metadata=metadata,dates=[m['target_date'] for m in metadata],available=np.ones(len(metadata),dtype=bool),baseline_center_f=np.full(len(metadata),center),outer_fold_id='OUTER_01',inner_fold_id='INNER_02')


class BaselineTests(unittest.TestCase):
    def test_leap_and_wrap(self):
        self.assertEqual(calendar_index(date(2024,2,29)),59)
        self.assertEqual(calendar_index(date(2023,3,1)),60)
        self.assertEqual(seasonal_distance(calendar_index(date(2021,12,31)),0),1)

    def test_reference_scipy_parity(self):
        for center in [-150,-40,-39.5,0,80,119.5,120,250]:
            for sigma in [.75,1.25,2,3]:
                np.testing.assert_allclose(mixture(center,[-3.4,0,1.2,6.8],sigma,'scipy'),mixture(center,[-3.4,0,1.2,6.8],sigma),atol=3e-15,rtol=1e-11)

    def fixture(self,n=40):
        train=batch([date(2021,1,1)+timedelta(days=i) for i in range(n)])
        y=train.baseline_center_f+np.tile([2.,-2.],n)
        return train,ResidualFit(train,y),batch([date(2022,1,20)],split='ASSESS',center=80.)

    def test_translation_and_exact_issue(self):
        _,fit,query=self.fixture()
        rows=list(fit.forecast(query,dict(seasonal_half_width_days=45,kernel_sigma_f=.75),'scipy'))
        self.assertEqual(len(rows),2)
        np.testing.assert_allclose(rows[0][2],mixture(82.,[0],.75,'scipy'))
        np.testing.assert_allclose(rows[1][2],mixture(78.,[0],.75,'scipy'))
        self.assertEqual(rows[0][4]['pool_days'],40)

    def test_pool_39_abstains(self):
        _,fit,query=self.fixture(39)
        self.assertEqual(next(fit.forecast(query,dict(seasonal_half_width_days=45,kernel_sigma_f=2)))[3],'INSUFFICIENT_RESIDUAL_POOL')

    def test_missing_query_abstains(self):
        _,fit,query=self.fixture();query.available[0]=False
        self.assertEqual(next(fit.forecast(query,dict(seasonal_half_width_days=45,kernel_sigma_f=2)))[3],'MISSING_CENTER')

    def test_missing_train_not_imputed(self):
        train,_,query=self.fixture();train.available[0]=False
        fit=ResidualFit(train,np.full(80,70))
        self.assertEqual(fit.counts(query,45).tolist(),[39,40])

    def test_duplicate_train_day_rejected(self):
        train,_,_=self.fixture();train.metadata.append(train.metadata[0]);train.available=np.ones(81,dtype=bool);train.baseline_center_f=np.full(81,70.)
        with self.assertRaises(s0.ContractError):ResidualFit(train,np.full(81,70))

    def test_assessment_fit_forbidden(self):
        b=batch([date(2022,1,1)],split='ASSESS')
        with self.assertRaises(s0.ContractError):ResidualFit(b,[70,70])

    def test_one_day_gap_rejected(self):
        train,fit,_=self.fixture();query=batch([max(train.dates)+timedelta(days=1)],split='ASSESS')
        with self.assertRaises(s0.ContractError):list(fit.forecast(query,dict(seasonal_half_width_days=45,kernel_sigma_f=2)))

    def test_tuning_equal_days_not_rows(self):
        p=np.array([mixture(70,[0],1),mixture(70,[0],1),mixture(75,[0],1)])
        d=[date(2022,1,1),date(2022,1,1),date(2022,1,2)]
        losses=day_losses(p,[70,70,70],d)
        self.assertEqual(len(losses),2)
        self.assertGreater(np.mean(list(losses.values())),sum([losses[str(d[0])]*2,losses[str(d[2])]])/3)

    def test_support_coverage_counts_missing_days(self):
        days=[date(2021,1,1)+timedelta(days=i) for i in range(120)]
        summary=support_summary(days,[i<60 for i in range(120)])
        self.assertTrue(summary['included']);self.assertEqual(summary['dayweighted_coverage'],.5)
        self.assertFalse(support_summary(days,[i<59 for i in range(120)])['included'])

    def test_tie_prefer_wider_window_then_kernel(self):
        c=[dict(candidate_id=str(i),parameters=dict(seasonal_half_width_days=w,kernel_sigma_f=k)) for i,(w,k) in enumerate([(45,3),(90,.75),(90,3)])]
        chosen,_=choose(c,{str(i):{'day':1+(1e-11 if i==2 else 0)} for i in range(3)})
        self.assertEqual(chosen['candidate_id'],'2')

    def test_incomparable_candidate_support_rejected(self):
        c=[dict(candidate_id='a'),dict(candidate_id='b')]
        with self.assertRaises(s0.ContractError):choose(c,{'a':{'x':1},'b':{'y':1}})

    def test_outer_label_access_rejected_before_io(self):
        b=batch([date(2023,1,1)],split='ASSESS');b.inner_fold_id=None
        with self.assertRaises(s0.ContractError):inner_labels(None,b,[],[True,True])

    def test_immutable_checkpoint_and_tampering(self):
        _,fit,query=self.fixture()
        c=dict(model_id='B0_H',candidate_id='test',parameters=dict(seasonal_half_width_days=45,kernel_sigma_f=1.25))
        identity=dict(run_sha='0'*64,code_sha='1'*64,inputs={'fixture':'2'*64})
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'unit';a=create_unit(p,fit,query,c,identity,'scipy')
            b=create_unit(p,fit,query,c,identity,'scipy');self.assertEqual(a,b)
            _,rows=verify_unit(p);self.assertEqual(len(rows),2)
            self.assertFalse(any('y_audited_f' in row for row in rows))
            with (p/'fit.parquet').open('ab') as f:f.write(b'tamper')
            with self.assertRaises(s0.ContractError):verify_unit(p)

    def test_failed_unit_is_not_committed(self):
        _,fit,query=self.fixture();c=dict(parameters=dict(seasonal_half_width_days=45,kernel_sigma_f=1.25))
        identity=dict(run_sha='0'*64,code_sha='1'*64,inputs={'fixture':'2'*64})
        with tempfile.TemporaryDirectory() as tmp:
            with patch('r14_s2.workflow.publish_partition',side_effect=RuntimeError('interrupt')):
                with self.assertRaises(RuntimeError):create_unit(Path(tmp)/'unit',fit,query,c,identity,'scipy')
            self.assertEqual(list(Path(tmp).iterdir()),[])


class WorkflowTests(unittest.TestCase):
    def test_full_synthetic_orchestration_and_resume(self):
        from r14_s2 import workflow
        contract=s0.read_json(ROOT/'config/experiment.json')
        class FakeLoader:
            def __init__(self,*args):self.contract=contract
            def load_features(self,model,outer,split='TRAIN',inner=None):
                specs=contract['folds']['inner' if inner else 'outer']
                spec=next(s for s in specs if s.get('inner_fold_id',s.get('outer_fold_id'))==(inner or outer))
                q=date.fromisoformat(spec['assessment_start'])
                days=[q-timedelta(days=380)+timedelta(days=i) for i in range(40)] if split=='TRAIN' else [q]
                b=batch(days,model,split,minutes=(0,));b.outer_fold_id=outer;b.inner_fold_id=inner
                return b
            def training_labels(self,b):return np.full(len(b.metadata),70.)
            def input_hashes(self):return {'synthetic':'a'*64}
        identity={'code':{'test':'b'*64},'engine':'scipy','purpose':'synthetic'}
        with tempfile.TemporaryDirectory() as tmp,patch.object(workflow,'binding',return_value=identity),patch.object(workflow,'DevelopmentLoader',FakeLoader),patch.object(workflow,'inner_labels',return_value=np.array([70])),patch.object(workflow,'support_summary',return_value={'included':True,'eligible_days':60,'dayweighted_coverage':1.}):
            root=Path(tmp)
            workflow.run(ROOT,root,root,'scipy',max_units=1)
            self.assertEqual(s0.read_json(root/'status.json')['state'],'PAUSED')
            first=root/'units'/next((root/'units').iterdir()).name/'unit.json';initial=s0.sha256(first)
            workflow.run(ROOT,root,root,'scipy')
            self.assertEqual(initial,s0.sha256(first))
            self.assertEqual(s0.read_json(root/'status.json')['state'],'COMPLETE')
            self.assertEqual(len(s0.read_json(root/'BASELINE_RELEASE.json')['units']),366)
            self.assertEqual(workflow.validate_run(ROOT,root,root)['units'],366)
            with patch.object(workflow,'binding',return_value={'code':{},'engine':'scipy'}):
                with self.assertRaises(s0.ContractError):workflow.run(ROOT,root,root,'scipy')

    def test_inner_labels_need_every_configuration(self):
        from r14_s2.workflow import inner_labels
        b=batch([date(2022,1,1)],split='ASSESS')
        loader=SimpleNamespace(experiment=ROOT)
        with self.assertRaises(s0.ContractError):inner_labels(loader,b,[],[True,True])



class InnerAccessTests(unittest.TestCase):
    def test_inner_truth_source_and_scope(self):
        from r14_s2 import workflow
        import pyarrow as pa
        import pyarrow.parquet as pq
        from contextlib import ExitStack
        b=batch([date(2022,1,1)],split='ASSESS')
        candidates=[c for c in s0.read_json(ROOT/'config/candidates.json')['candidates'] if c['model_id']=='B0_H']
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);source=root/'source.parquet';catalog=root/'catalog.parquet'
            pq.write_table(pa.Table.from_pylist([{'target_date':date(2022,1,1),'y_audited_f':71}]),source)
            t={'catalog':'catalog.parquet','catalog_authorization_columns':['target_date','truth_group','label_available_for_supervised_use','source_artifact_path','source_artifact_sha256'],'source_path':'source.parquet','source_sha256':s0.sha256(source),'source_max_date':'2025-09-06'}
            def write_catalog(role='development'):
                pq.write_table(pa.Table.from_pylist([{'target_date':date(2022,1,1),'truth_group':role,'label_available_for_supervised_use':True,'source_artifact_path':t['source_path'],'source_artifact_sha256':t['source_sha256']}]),catalog)
            write_catalog()
            paths=[];records={}
            for c in candidates:
                p=root/c['candidate_id'];p.mkdir();paths.append(p)
                m={'model_id':'B0_H','inner_fold_id':'INNER_02','outer_fold_id':'OUTER_01','configuration_sha256':digest(c)}
                (p/'manifest.json').write_text(json.dumps(m));records[str(p)]=(m,b.metadata)
            loader=SimpleNamespace(experiment=ROOT,supplement={'truth_accessor':t},_input=lambda rel:root/rel,fold_dates=lambda *args:[date(2022,1,1)])
            calls=[];original=workflow.read_dates
            def tracked(path,cols,dates):
                calls.append((Path(path).name,tuple(cols),tuple(dates)))
                return original(path,cols,dates)
            with patch.object(workflow,'read_partition',side_effect=lambda p:records[str(p)]),patch.object(workflow,'read_dates',side_effect=tracked):
                self.assertEqual(workflow.inner_labels(loader,b,paths,[True,True]).tolist(),[71,71])
                self.assertTrue(all('y_audited_f' not in cols for name,cols,_ in calls if name=='catalog.parquet'))
                self.assertTrue(all(set(ds)=={date(2022,1,1)} for _,_,ds in calls))
                calls.clear();write_catalog('reserved')
                with self.assertRaises(s0.ContractError):workflow.inner_labels(loader,b,paths,[True,True])
                self.assertFalse(any('y_audited_f' in cols for _,cols,_ in calls))
                write_catalog()
                pq.write_table(pa.Table.from_pylist([{'target_date':date(2022,1,1),'y_audited_f':71},{'target_date':date(2025,9,7),'y_audited_f':90}]),source)
                calls.clear()
                with self.assertRaises(s0.ContractError):workflow.inner_labels(loader,b,paths,[True,True])
                self.assertFalse(any('y_audited_f' in cols for _,cols,_ in calls))

if __name__=='__main__':unittest.main()
