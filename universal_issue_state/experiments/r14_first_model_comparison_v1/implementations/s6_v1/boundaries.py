"""Successor boundary primitive. Does not alter or wrap frozen S2/S4 runners."""
from datetime import date,timedelta

def cutoff(first_assessment_date,lag_days=2):
    if lag_days != 2: raise ValueError('Registered lag is two calendar days')
    return date.fromisoformat(first_assessment_date)-timedelta(days=lag_days)

def eligible_dates(dates,first_assessment_date,allowed_start,allowed_end):
    bound=cutoff(first_assessment_date);lo=date.fromisoformat(allowed_start);hi=date.fromisoformat(allowed_end)
    if lo>hi: raise ValueError('Reversed evidence interval')
    if len(dates)!=len(set(dates)): raise ValueError('Duplicate target dates')
    return [d for d in dates if lo<=date.fromisoformat(d)<=min(hi,bound)]

def assert_eligible(dates,first_assessment_date,allowed_start,allowed_end):
    if list(dates)!=eligible_dates(dates,first_assessment_date,allowed_start,allowed_end):
        raise ValueError('Unavailable or unauthorized label date')

def require_forward_lineage(row):
    """Each row records label dates actually consumed at each decision stage."""
    for stage in ('base_fit','base_selection','preprocessing','reliability_fit','threshold_fit'):
        record=row[stage]
        decision=record['first_assessment_date']
        if date.fromisoformat(decision)>date.fromisoformat(row['target_date']):
            raise ValueError('Decision occurs after forecast target')
        assert_eligible(record['label_dates'],decision,row['allowed_start'],row['allowed_end'])
    return True
