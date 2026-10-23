from pathlib import Path
from dataclasses import replace
import copy,json
import numpy as np
from s0 import require,read_json,sha256
from r14_s1.data import DevelopmentLoader,FeatureBatch,kelvin_to_fahrenheit

class Loader(DevelopmentLoader):
    def __init__(self,project,experiment,implementation):
        super().__init__(project,experiment)
        self.s3=read_json(Path(implementation)/'config.json')
        require(sha256(self.experiment/'manifests/S1_RELEASE.json')==self.s3['parent_s1_sha256'],'S1 parent mismatch')
        reg=self._input(self.s3['registry']);require(sha256(reg)==self.s3['registry_sha256'],'S3 registry mismatch')
        entries={x['name']:x for x in read_json(reg)['features']}
        raw=sorted({v for spec in self.s3['features'].values() for v in spec[1:]}|{self.s3['center']})
        self.features=copy.deepcopy(self.features);self.features['registry_entries'].update(entries)
        self.features['sets']['ANEN']=raw
        self.features['sets']['GAM']=sorted(set(raw+self.s3['clocks']))
    def load_features(self,*args,**kwargs):
        batch=super().load_features(*args,**kwargs)
        raw={n:batch.X[:,i] for i,n in enumerate(batch.columns)};columns=[];values=[]
        for name,spec in self.s3['features'].items():
            value=raw[spec[1]] if spec[0]=='identity' else raw[spec[1]]-raw[spec[2]]
            columns.append(name);values.append(value)
        for name in [self.s3['center']]+[x for x in self.s3['clocks'] if x in raw]:
            columns.append(name);values.append(raw[name])
        X=np.column_stack(values);available=np.isfinite(X).all(axis=1)
        missing=tuple(tuple(n for n,v in zip(columns,row) if not np.isfinite(v)) for row in X)
        X.setflags(write=False);available.setflags(write=False)
        return replace(batch,columns=tuple(columns),X=X,available=available,missing_features=missing)

def get(batch,name):return batch.X[:,batch.columns.index(name)]
def center(batch):return kelvin_to_fahrenheit(get(batch,'q05_local_retained_max'))
def weather(batch,config):return np.column_stack([get(batch,n) for n in config['features']])
def check_training(batch,y):
    y=np.asarray(y);require(batch.split=='TRAIN','Training role required')
    require(y.shape==(len(batch.metadata),) and np.isfinite(y).all() and np.all(y==np.floor(y)) and np.all((y>=-40)&(y<=120)),'Invalid training labels')
    require(len({(m['target_date'],m['local_minutes_since_0200']) for m in batch.metadata})==len(batch.metadata),'Duplicate day/issue')
    require(batch.available.any(),'No complete training rows')
