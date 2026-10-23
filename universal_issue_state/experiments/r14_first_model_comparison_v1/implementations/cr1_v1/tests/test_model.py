import sys,unittest,json
from pathlib import Path
import numpy as np
from scipy.special import expit
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from model import objective,day_weights,fit,predict,threshold,admit,design
REG={'estimator':{'ridge_lambda':.01,'logit_clip':[1e-6,1-1e-6]},'chronology':{'minimum_fit_days':2,'minimum_fit_hits':1,'minimum_fit_misses':1},'weather_features':[{'column':'x','transform':'log1p'},{'column':'z','transform':'absolute'}]}
class Models(unittest.TestCase):
 def test_analytic_gradient(self):
  rng=np.random.default_rng(22);X=np.column_stack([np.ones(50),rng.normal(size=(50,4))]);y=rng.integers(0,2,50);w=np.ones(50)/50;b=rng.normal(size=5);v,g=objective(b,X,y,w,.01)
  fd=np.array([(objective(b+np.eye(5)[i]*1e-6,X,y,w,.01)[0]-objective(b-np.eye(5)[i]*1e-6,X,y,w,.01)[0])/2e-6 for i in range(5)])
  np.testing.assert_allclose(g,fd,atol=1e-8)
 def test_extreme_logits_stable(self):
  v,g=objective(np.array([1000.,-1000]),np.array([[1.,0],[1,2]]),np.array([0.,1]),np.array([.5,.5]),.01);self.assertTrue(np.isfinite(v) and np.all(np.isfinite(g)))
 def test_equal_day_mass(self):np.testing.assert_allclose(day_weights(['a','a','b'],[1,1,1]),[.25,.25,.5])
 def test_intercept_only_known_answer(self):
  X=np.ones((20,2));y=np.array([1.]*5+[0.]*15);s=fit(X,y,np.arange(20),np.ones(20,bool),REG);self.assertEqual(s['keep'],[False,False]);np.testing.assert_allclose(predict(s,X,np.ones(20,bool)),.25,atol=1e-5)
 def test_assessment_cannot_change_scaler(self):
  X=np.arange(20.)[:,None];mask=np.arange(20)<10;y=np.arange(20)%2;days=np.arange(20);s=fit(X,y,days,mask,REG);X[10:]=1e9;t=fit(X,y,days,mask,REG);self.assertEqual(s,t)
 def test_serialized_predictions(self):
  X=np.arange(20.)[:,None];s=fit(X,np.arange(20)%2,np.arange(20),np.ones(20,bool),REG);np.testing.assert_array_equal(predict(s,X,np.ones(20,bool)),predict(json.loads(json.dumps(s)),X,np.ones(20,bool)))
 def test_missing_predict_abstains(self):
  X=np.ones((20,1));s=fit(X,np.arange(20)%2,np.arange(20),np.ones(20,bool),REG);m=np.arange(20)>0;p=predict(s,X,m);self.assertTrue(np.isnan(p[0]))
 def test_minimum_support_fails(self):
  with self.assertRaises(ValueError):fit(np.ones((20,1)),np.zeros(20),np.arange(20),np.ones(20,bool),REG)
 def test_threshold_ties(self):
  p=np.array([.2,.4,.4,.8]);t=threshold(p,['a','a','b','b'],np.full(4,2),np.ones(4,bool),.5,2);self.assertEqual(t,.4);self.assertEqual(admit(p,np.ones(4,bool),t).sum(),3)
 def test_threshold_population_weights(self):
  p=np.array([.2,.3,.9]);t=threshold(p,['a','a','b'],[2,2,1],np.ones(3,bool),.5,2);self.assertEqual(t,.3)
 def test_no_admission_and_all_coverage(self):
  p=np.array([.1,np.nan]);self.assertFalse(admit(p,[1,0],.2).any());self.assertEqual(admit(p,[1,0],None).tolist(),[True,False])
 def test_feature_transforms_and_negative(self):
  d,m=design([.2,.3],[0,840],np.array([0.,1]),np.array([1.,0]),{'x':np.array([3.,-1]),'z':np.array([-2.,3.])},REG);self.assertEqual(m.tolist(),[True,False]);self.assertAlmostEqual(d['R2'][0,-2],np.log(4));self.assertEqual(d['R2'][0,-1],2);self.assertEqual(d['R1'].shape,(2,7))
if __name__=='__main__':unittest.main()
