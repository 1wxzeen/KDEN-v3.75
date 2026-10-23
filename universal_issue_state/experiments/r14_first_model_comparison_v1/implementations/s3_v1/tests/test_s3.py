from pathlib import Path
import os,sys,json,unittest,tempfile
from datetime import date,timedelta
from dataclasses import replace
import numpy as np
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT));sys.path.insert(0,str(Path(os.environ['R14_EXPERIMENT_ROOT'])/'src'))
import s0
from r14_s1.data import FeatureBatch,legal_issue_times
from r14_s1.probability import normal_pmf
from r14_s3.probability import likelihood,pmf
from r14_s3.gam import GAM,objective
from r14_s3.anen import Analog,scale_fit,coordinate_weights
CFG=json.loads((ROOT/'config.json').read_text())

def fixture(model='ANEN',n=100,year=2021):
    rng=np.random.default_rng(33);days=[date(year,1,1)+timedelta(days=i) for i in range(n)];columns=list(CFG['features'])+[CFG['center']]+CFG['clocks'];X=rng.normal(size=(n,len(columns)))
    def put(c,x):X[:,columns.index(c)]=x
    put(CFG['center'],295+rng.normal(0,3,n));put('thermal_state',290+rng.normal(0,3,n));put('thermal_850',285+rng.normal(0,3,n))
    put('clock_issue_minutes_since_0200',np.zeros(n));put('clock_local_dst_flag',np.zeros(n));put('clock_target_doy_sin',np.sin(np.arange(n)*2*np.pi/366));put('clock_target_doy_cos',np.cos(np.arange(n)*2*np.pi/366))
    for c in ['clock_wrfsfcf_cycle_age_minutes','clock_wrfsubhf_cycle_age_minutes']:put(c,np.full(n,120))
    meta=tuple({'target_date':d,'local_minutes_since_0200':0,'issue_state_id':str(d),'issue_time_utc':legal_issue_times(d)[0],'issue_count_for_target_day':len(legal_issue_times(d)),'statistical_group_id':'KDEN_DAY_'+str(d)} for d in days)
    b=FeatureBatch(model,tuple(columns),X,meta,np.ones(n,dtype=bool),tuple(() for _ in days),{'fixture':'0'*64},'OUTER_01','INNER_02','TRAIN' if year==2021 else 'ASSESS')
    y=np.rint((X[:,columns.index(CFG['center'])]-273.15)*1.8+32+2+.5*X[:,columns.index('forecast_revision')]+rng.normal(0,1,n)).astype(int)
    return b,y

class ProbabilityTests(unittest.TestCase):
    def test_normal_reference(self):
        for mu in [-80,-40,0,90,120,160]:
            for sigma in [.25,1,20]:np.testing.assert_allclose(pmf(mu,sigma)[0],normal_pmf(mu,sigma),atol=2e-15)
    def test_t_normalized(self):
        for mu in [-200,0,200]:self.assertAlmostEqual(pmf(mu,.25,'t5').sum(),1.)
    def test_analytic_derivatives(self):
        for family in ['normal','t5']:
            for y,mu,sigma in [(-40,0,2),(120,90,3),(90,91,.75),(10,-20,1),(30,0,.25),(0,30,.25)]:
                n,a,b=likelihood(y,mu,sigma,family);h=1e-5
                da=(likelihood(y,mu+h,sigma,family)[0]-likelihood(y,mu-h,sigma,family)[0])/(2*h)
                db=(likelihood(y,mu,sigma*np.exp(h),family)[0]-likelihood(y,mu,sigma*np.exp(-h),family)[0])/(2*h)
                self.assertLess(abs(a-da)/max(1,abs(da)),1e-5);self.assertLess(abs(b-db)/max(1,abs(db)),1e-5)
    def test_objective_gradient(self):
        rng=np.random.default_rng(12);A=np.c_[np.ones(30),rng.normal(size=(30,3))];B=np.c_[np.ones(30),rng.normal(size=(30,2))];theta=rng.normal(0,.2,7);y=rng.integers(65,75,30)
        for family in ['normal','t5']:
            args=(A,B,np.full(30,70),y,np.full(30,1/30),.01,.1,family);v,g=objective(theta,*args)
            for j in range(7):
                step=np.eye(7)[j]*1e-5;numeric=(objective(theta+step,*args)[0]-objective(theta-step,*args)[0])/2e-5
                self.assertLess(abs(g[j]-numeric)/max(1,abs(numeric)),1e-5)

class AnalogTests(unittest.TestCase):
    def test_group_balance(self):
        w=coordinate_weights(['a','b','c'],[['a','b'],['c']],np.ones(3,dtype=bool));np.testing.assert_allclose(w,[.25,.25,.5])
    def test_scaling_fallback_and_constants(self):
        _,s,a=scale_fit(np.array([[0,1],[0,1],[0,1],[0,1],[10,1]]));self.assertTrue(a[0]);self.assertFalse(a[1]);self.assertGreater(s[0],0)
    def test_prediction_support_weights(self):
        b,y=fixture();q,_=fixture(year=2022,n=2);m=Analog(b,y,CFG);params=dict(seasonal_half_width_days=90,neighbors=15,bandwidth_multiplier=1.,kernel_sigma_f=1.25)
        rows=list(m.forecast(q,params));self.assertTrue(all(r[4] is None for r in rows));d=rows[0][5];self.assertEqual(len(d['neighbors']),15);self.assertAlmostEqual(sum(d['weights']),1);self.assertLessEqual(d['effective_sample_size'],15+1e-10)
        self.assertTrue(all(x.startswith('2021') for x in d['neighbors']))
        refs=m.references(0,90,15);self.assertEqual(len(refs),100)
    def test_infeasible_k_no_shrink(self):
        b,y=fixture(n=40);q,_=fixture(year=2022,n=1);m=Analog(b,y,CFG)
        row=next(m.forecast(q,dict(seasonal_half_width_days=90,neighbors=60,bandwidth_multiplier=1.,kernel_sigma_f=1.25)));self.assertEqual(row[4],'INFEASIBLE_NEIGHBOR_COUNT')
    def test_missing_abstention(self):
        b,y=fixture();q,_=fixture(year=2022,n=1);q=replace(q,available=np.array([False]));r=next(Analog(b,y,CFG).forecast(q,dict(seasonal_half_width_days=90,neighbors=15,bandwidth_multiplier=1.,kernel_sigma_f=1.25)));self.assertEqual(r[4],'MISSING_REQUIRED_INPUT')

class GAMTests(unittest.TestCase):
    def test_models_fit_and_predict(self):
        for model in ['GAM_LS_NORMAL','GAM_LOCATION_NORMAL','GAM_LS_T5']:
            b,y=fixture(model,n=100);q,_=fixture(model,year=2022,n=3);g=GAM(b,y,CFG,dict(lambda_mu=.01,lambda_scale=.1));rows=list(g.forecast(q));self.assertTrue(all(r[4] is None for r in rows));self.assertTrue(any(s['accepted'] for s in g.starts));self.assertTrue(all(.25<=r[5]['scale_f']<=20 for r in rows))
            if model=='GAM_LOCATION_NORMAL':self.assertEqual(g.scale.dimension,1)
    def test_no_assessment_fit(self):
        b,y=fixture('GAM_LS_NORMAL',year=2022)
        with self.assertRaises(s0.ContractError):GAM(b,y,CFG,dict(lambda_mu=.01,lambda_scale=.1))
    def test_training_only_design(self):
        b,y=fixture('GAM_LS_NORMAL');g=GAM(b,y,CFG,dict(lambda_mu=.01,lambda_scale=.1));q,_=fixture('GAM_LS_NORMAL',year=2022,n=2);before=g.location.mean.copy();q.X[:,q.columns.index('thermal_state')]=1000
        rows=list(g.forecast(q));np.testing.assert_equal(before,g.location.mean);self.assertTrue(all(r[5]['out_of_range'] for r in rows))



class AdditionalTests(unittest.TestCase):
    def test_constant_coordinates_abstain(self):
        b,y=fixture();q,_=fixture(year=2022,n=1)
        for name in CFG['features']:b.X[:,b.columns.index(name)]=1
        row=next(Analog(b,y,CFG).forecast(q,dict(seasonal_half_width_days=90,neighbors=15,bandwidth_multiplier=1.,kernel_sigma_f=1.25)))
        self.assertEqual(row[4],'ALL_COORDINATES_CONSTANT')
    def test_zero_distance_uniform_and_stable_ties(self):
        b,y=fixture();q,_=fixture(year=2022,n=1)
        for name in CFG['features']:
            j=b.columns.index(name);b.X[:50,j]=0;b.X[50:,j]=1;q.X[:,q.columns.index(name)]=0
        row=next(Analog(b,y,CFG).forecast(q,dict(seasonal_half_width_days=90,neighbors=15,bandwidth_multiplier=1.,kernel_sigma_f=1.25)))
        np.testing.assert_allclose(row[5]['weights'],np.full(15,1/15));self.assertEqual(row[5]['neighbors'],[str(date(2021,1,1)+timedelta(days=i)) for i in range(15)])
    def test_no_self_in_reference(self):
        b,y=fixture(n=40);a=Analog(b,y,CFG);self.assertEqual(len(a.references(0,90,15)),0)
    def test_future_assessment_rejected(self):
        b,y=fixture();q=replace(b,split='ASSESS')
        with self.assertRaises(s0.ContractError):next(Analog(b,y,CFG).forecast(q,dict(seasonal_half_width_days=90,neighbors=15,bandwidth_multiplier=1.,kernel_sigma_f=1.25)))
    def test_duplicate_training_rejected(self):
        b,y=fixture();b=replace(b,metadata=(b.metadata[0],)*len(b.metadata))
        with self.assertRaises(s0.ContractError):Analog(b,y,CFG)
    def test_gam_solver_failure_reported(self):
        from unittest.mock import patch
        with patch('r14_s3.gam.minimize',side_effect=ValueError('test failure')):
            b,y=fixture('GAM_LS_NORMAL')
            try:GAM(b,y,CFG,dict(lambda_mu=.01,lambda_scale=.1));self.fail('should fail')
            except s0.ContractError as e:self.assertEqual(len(e.starts),3)
    def test_day_weights_equal_days(self):
        from r14_s1.data import day_weights
        days=[date(2021,1,1)]*2+[date(2021,1,2)]
        np.testing.assert_allclose(day_weights(days,np.ones(3,dtype=bool)),[.25,.25,.5])
    def test_t5_derivative_endpoints(self):
        for y in [-40,120]:
            loss,a,b=likelihood(y,70.,.25,'t5');self.assertTrue(np.isfinite([loss,a,b]).all())



class PersistenceTests(unittest.TestCase):
    def test_save_restore_forecasts(self):
        from r14_s3.runtime import fit_artifact,load_fit,save,digest
        for model in ['ANEN','GAM_LS_NORMAL','GAM_LOCATION_NORMAL','GAM_LS_T5']:
            b,y=fixture(model);q,_=fixture(model,year=2022,n=2)
            params=dict(seasonal_half_width_days=90,neighbors=15,bandwidth_multiplier=1.,kernel_sigma_f=1.25) if model=='ANEN' else dict(lambda_mu=.01,lambda_scale=.1)
            fitted=Analog(b,y,CFG) if model=='ANEN' else GAM(b,y,CFG,params)
            ident={'model':model,'parameters':params,'input_hashes':{'fixture':'0'*64},'configuration_sha256':digest({'spec':CFG,'parameters':params,'model':model})}
            with tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp);fit_artifact(root,fitted,y,ident)
                u={'outer':'OUTER_01','inner':'INNER_02','files':{p.name:s0.sha256(p) for p in root.iterdir()}};u['record_sha256']=digest(u);save(root/'UNIT.json',u)
                restored=load_fit(root,CFG)
                for a,c in zip(fitted.forecast(q,params),restored.forecast(q,params)):np.testing.assert_allclose(a[2],c[2],atol=1e-15)



class UnitTests(unittest.TestCase):
    def test_atomic_unit_and_no_overwrite(self):
        from unittest.mock import patch
        from r14_s3 import runtime
        contract=json.loads((Path(os.environ['R14_EXPERIMENT_ROOT'])/'config/experiment.json').read_text())
        class FakeLoader:
            def __init__(self,*args):self.s3=CFG;self.contract=contract
            def load_features(self,model,outer,split,inner):return fixture(model,n=100 if split=='TRAIN' else 2,year=2021 if split=='TRAIN' else 2022)[0]
            def training_labels(self,b):return fixture(b.model_id)[1]
            def input_hashes(self):return {'fixture':'0'*64}
        c=runtime.candidates(ROOT,'ANEN')[0]
        with tempfile.TemporaryDirectory() as tmp,patch.object(runtime,'validate'),patch.object(runtime,'Loader',FakeLoader):
            dest=Path(tmp)/'unit';u=runtime.unit(ROOT,ROOT,ROOT,dest,'ANEN',c['candidate_id'],'OUTER_01','INNER_02');self.assertTrue((dest/'UNIT.json').exists());self.assertEqual(u['status'],'S3_CANDIDATE_UNIT_COMPLETE_NOT_SELECTED')
            self.assertEqual(s0.read_json(dest.with_suffix('.status.json'))['state'],'COMPLETE')
            with self.assertRaises(s0.ContractError):runtime.unit(ROOT,ROOT,ROOT,dest,'ANEN',c['candidate_id'],'OUTER_01','INNER_02')
    def test_s3_feature_transforms(self):
        # The S1 loader is already tested. Verify S3 expressions with real structure.
        from r14_s3.data import Loader
        from unittest.mock import patch
        source=['q05_local_asof_value','q05_local_remaining_max','q05_local_retained_max']
        source=sorted(set(source+[n for expr in CFG['features'].values() for n in expr[1:]]))
        b,_=fixture();x=np.full((len(b.metadata),len(source)),290.)
        x[:,source.index('q05_local_remaining_max')]=295.
        raw=replace(b,columns=tuple(source),X=x)
        obj=Loader.__new__(Loader);obj.s3=CFG
        with patch('r14_s1.data.DevelopmentLoader.load_features',return_value=raw):
            transformed=obj.load_features('ANEN','OUTER_01')
            np.testing.assert_equal(transformed.X[:,transformed.columns.index('heating_potential')],5.)
            self.assertIn('thermal_850',transformed.columns)



if __name__=='__main__':unittest.main()
