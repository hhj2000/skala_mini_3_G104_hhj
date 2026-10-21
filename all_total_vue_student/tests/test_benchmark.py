"""Metric correctness, benchmark labels, failure handling and blind judge contracts."""
import asyncio
import json
import random

import pytest
from eval.benchmark_metrics import (retrieval_scores, classification_counts, classification_scores, bootstrap_delta)
from eval.kharakteres_benchmark import (ROOT, load_dataset, Meter, structural_quality, judge_pair, summaries, paired_comparisons)


def test_rank_metrics_hand_calculated_and_empty_gold_not_perfect_recall():
    s=retrieval_scores(['irrelevant','a','b'],['a','b','c'],3)
    assert s['precision_at_k']==pytest.approx(2/3)
    assert s['recall_at_k']==pytest.approx(2/3)
    assert s['mrr']==.5
    assert 0<s['ndcg_at_k']<1
    empty=retrieval_scores([],[],3)
    assert empty['recall_at_k'] is None and empty['no_answer_correct']==1
    assert retrieval_scores(['x'],[],3)['no_answer_correct']==0
    assert retrieval_scores(['a'],['a'],3)['precision_at_k']==pytest.approx(1/3)
    with pytest.raises(ValueError): retrieval_scores(['a','a'],['a'],3)


def test_confusion_matrix_catches_false_positives_and_false_negatives():
    counts=classification_counts(['a','x'],['a','b'],['a','b','x','z'])
    assert counts==dict(tp=1,fp=1,fn=1,tn=1)
    scores=classification_scores(counts)
    assert scores['precision']==scores['recall']==scores['f1']==scores['accuracy']==.5
    with pytest.raises(ValueError): classification_counts(['unknown'],[],['known'])


def test_case_bootstrap_and_repeats_do_not_inflate_sample_size():
    d=bootstrap_delta([(0,1),(0,1)])
    assert d['ci95']==[1,1] and d['paired_cases']==2
    rows=[dict(task='generation',variant=v,case_id='g',metrics={'contract_pass':score}) for _ in range(4) for v,score in [('no_context',0),('vector',1)]]
    result=paired_comparisons(rows,104)[0]
    assert result['paired_cases']==1


def test_dataset_references_schemas_splits_and_author_preservation():
    data,docs=load_dataset(ROOT/'eval/datasets/kharakteres_v1.json')
    assert len(docs)==16
    assert {c['split'] for c in data['retrieval']}=={'dev','test'}
    from kharakteres.models import SpellInput
    request={'prompt':'빛을 부르는 나만의 주문','language_kind':'constructed','language':'별의 언어','author_incantation':'Aru','author_pronunciation':'아루','author_meaning':'빛','author_ipa':''}
    draft=SpellInput(name='별',incantation='Aru',language_kind='constructed',language='별의 언어',hangul_pronunciation='아루',literal_meaning='빛',effect=request['prompt'],elements=['light']).model_dump()
    assert all(structural_quality(draft,request,docs.values()).values())
    draft['hangul_pronunciation']='잘못된 전사'
    assert not structural_quality(draft,request,docs.values())['author_fields_preserved']


def test_budget_counts_failed_model_calls():
    class Broken:
        name='broken'
        def _chat(self,*a,**kw): raise ValueError('bad response')
    meter=Meter(1); model=meter.wrap(Broken(),'subject')
    with pytest.raises(ValueError): model._chat('','')
    assert meter.calls[0]['error']=='ValueError'
    with pytest.raises(RuntimeError,match='budget'): model._chat('','')
    assert len(meter.calls)==1


def test_judge_requires_full_checklist_and_bounded_integer_scores():
    class Judge:
        async def call_model(self,system,user,schema):
            self.input=json.loads(user)
            score=dict(instruction=4,consistency=4,originality=3,expression=3,criteria=[True],reason='근거')
            return json.dumps({'A':score,'B':score}),{}
    judge=Judge(); case={'request':{'prompt':'빛'},'criteria':['조명']}
    results,_=asyncio.run(judge_pair(judge,case,{'no_context':{'name':'a'},'vector':{'name':'b'}},[],random.Random(104)))
    assert results['vector']['passed']
    assert set(judge.input['candidates'])=={'A','B'} and 'variant' not in str(judge.input)
    case['criteria'].append('다른 기준')
    with pytest.raises(ValueError,match='checklist'):
        asyncio.run(judge_pair(judge,case,{'no_context':{},'vector':{}},[],random.Random(104)))


def test_independent_audit_detects_missing_cases_and_forged_scores():
    import copy
    import hashlib
    from eval.audit_kharakteres_report import audit
    path=ROOT/'eval/datasets/kharakteres_v1.json'
    data,_=load_dataset(path)
    manifest={'dataset_sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'tasks':['retrieval'],
              'backend':'fake','split':'dev','repeat':1,'k':3,'seed':104,'judge_enabled':False}
    rows=[]
    for case in data['retrieval']:
        if case['split']!='dev': continue
        for variant in ('keyword','vector'):
            returned=case['relevant_ids'][:3]
            rows.append(dict(task='retrieval',variant=variant,case_id=case['id'],repeat=0,
                             returned=[{'id':i} for i in returned],error=None,latency_ms=1,
                             metrics=retrieval_scores(returned,case['relevant_ids'],3)))
    report={'manifest':manifest,'complete':True,'rows':rows,'summary':summaries(rows,1),'paired_comparisons':paired_comparisons(rows,104)}
    assert audit(report,path)['integrity']=='passed'
    bad=copy.deepcopy(report); bad['rows'].pop()
    with pytest.raises(ValueError,match='Missing'): audit(bad,path)
    bad=copy.deepcopy(report); bad['rows'][0]['metrics']['recall_at_k']=.125
    with pytest.raises(ValueError,match='metric mismatch'): audit(bad,path)
