from pathlib import Path
import sys,unittest,json,tempfile
import numpy as np,joblib
P=Path(__file__).resolve().parents[1];sys.path[:0]=[str(P),str(P/'foundation/src')]
from models import training_weights,fit_imputer,transform,repair_quantiles,quantile_cdf,fit_model,predict_pmf,WeightedNormalBoost
from engine import select_candidate
from data import label_cutoff
CFG=json.loads((P/'config.json').read_text())
class Math(unittest.TestCase):
 def test_calendar_cutoff(self):self.assertEqual(label_cutoff('2025-01-01'),'2024-12-30');self.assertEqual(label_cutoff('2024-03-01'),'2024-02-28')
 def test_day_unit_weights(self):np.testing.assert_allclose(training_weights(['a','a','b']),[.5,.5,1])
 def test_weighted_initializer(self):
  m=WeightedNormalBoost();m.initial_weights_=np.array([.5,.5,1]);m.fit_init_params_to_marginal(np.array([0.,0.,10.]));np.testing.assert_allclose(m.init_params,[5,np.log(5)])
 def test_train_only_imputation(self):
  X=np.array([[1.,np.nan],[3,np.nan],[9,np.nan]]);s=fit_imputer(X,[.5,.5,1]);q=transform(np.array([[np.nan,100.]]),s);self.assertEqual(s['medians'],[3.,0.]);np.testing.assert_array_equal(q,[[3,100,1,0]]);self.assertEqual(s['all_missing'],[False,True])
 def test_crossing_and_ties_repaired(self):
  q=np.array([[9,8,7,6,5,4,3,2,1],[0]*9],float);r,c,e=repair_quantiles(q);self.assertTrue(np.all(np.diff(r,axis=1)>=.05-1e-12));self.assertEqual(c.tolist(),[True,False]);np.testing.assert_array_equal(r[:,4],[5,0])
 def test_cdf_knots_and_tails(self):
  q=np.arange(9.)[None,:];a=CFG['xgb']['quantiles'];F=quantile_cdf(q,np.arange(9.),a);np.testing.assert_allclose(F[0],a);F=quantile_cdf(q,np.array([-1e6,1e6]),a);np.testing.assert_allclose(F,[[0,1]])
 def test_selection_excludes_late_day(self):
  c=[{'id':'a','depth':2,'rounds':200},{'id':'b','depth':3,'rounds':200}];cfg=json.loads(json.dumps(CFG));cfg['selection']['minimum_inner_days']=1;records=[]
  for i in range(2):
   for x in c:records.append({'candidate':x,'status':'COMPLETE','daily_nll':{f'202{2+i}-01-01':1 if x['id']=='a' else 2,**({'2024-12-31':1000 if x['id']=='a' else 0} if i==1 else {})}})
  r=select_candidate(records,c,'2024-12-30',cfg);self.assertEqual(r['selected']['id'],'a');self.assertEqual(r['candidate_scores']['a']['max_label_date'],'2023-01-01')
 def test_failed_candidate_not_cherry_picked(self):
  cfg=json.loads(json.dumps(CFG));cfg['selection']['minimum_inner_days']=1;c=[{'id':'a','depth':2,'rounds':200}];r=[{'candidate':c[0],'status':'INVALID_MODEL'},{'candidate':c[0],'status':'COMPLETE','daily_nll':{'2023-01-01':0}}]
  with self.assertRaises(ValueError):select_candidate(r,c,'2024-12-30',cfg)
 def test_models_fit_pmf_and_serialization(self):
  rng=np.random.default_rng(92);X=rng.normal(size=(300,4));X[::9,1]=np.nan;y=np.nan_to_num(X[:,0])+rng.normal(size=300);days=np.repeat(np.arange(100),3)
  for family in ['XGB_QUANTILE','NGB_NORMAL']:
   with self.subTest(family=family):
    c={'id':'synthetic','family':family,'depth':2,'rounds':8};fit=fit_model(X,y,days,c,CFG);p,_,_=predict_pmf(fit,X[:20],np.full(20,90),CFG);self.assertEqual(p.shape,(20,161));self.assertTrue(np.all(p>=0));np.testing.assert_allclose(p.sum(axis=1),1,atol=1e-12)
    with tempfile.TemporaryDirectory() as tmp:
     path=Path(tmp)/'m.joblib';joblib.dump(fit,path);p2,_,_=predict_pmf(joblib.load(path),X[:20],np.full(20,90),CFG);np.testing.assert_allclose(p,p2,atol=1e-12)
if __name__=='__main__':unittest.main()
