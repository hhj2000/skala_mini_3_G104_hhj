"""모델 호출 없이 고정 정답표와 원본 행에서 지표·누락·중복·통계를 재계산한다.

검산 통과는 실험 기록의 일관성을 뜻한다. 라벨 자체의 타당성, LLM 채점의 진실성,
서비스 품질 목표 달성이나 실사용 전반의 검증을 대신하지 않는다.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from eval.kharakteres_benchmark import load_dataset, summaries, paired_comparisons, structural_quality, KINDS
from eval.benchmark_metrics import retrieval_scores, classification_counts, classification_scores


def audit(report, dataset):
    data, docs=load_dataset(dataset)
    m=report['manifest']
    if hashlib.sha256(dataset.read_bytes()).hexdigest()!=m['dataset_sha256']:
        raise ValueError('Dataset fingerprint mismatch')
    if not report['complete']:
        raise ValueError('Incomplete run')
    expected=set()
    for section, variants in [('retrieval',{'retrieval':['keyword','vector']}),
                              ('conflicts',{'conflict_rules':['name_only','rules'],**({'conflict_ai':['no_findings','model']} if m['backend']!='fake' else {})}),
                              ('generation',{'generation':['no_context','vector']})]:
        if section not in m['tasks']: continue
        for case in data[section]:
            if case['split']!=m['split']: continue
            for repeat in range(m['repeat']):
                for task,conditions in variants.items():
                    for variant in conditions: expected.add((task,variant,case['id'],repeat))
    actual=[(r['task'],r['variant'],r['case_id'],r['repeat']) for r in report['rows']]
    if len(actual)!=len(set(actual)) or set(actual)!=expected:
        raise ValueError('Missing, duplicate or unexpected case/condition/repeat')
    for row in report['rows']:
        if row['error'] or row.get('judge_error'):
            raise ValueError('Run contains model/retrieval/judge errors; inspect raw evidence')
        task=row['task']; metric=row['metrics']
        if task=='retrieval':
            case=next(c for c in data['retrieval'] if c['id']==row['case_id'])
            predicted=[s['id'] for s in row['returned']]
            if any(i not in docs or docs[i]['world']!=case['world'] for i in predicted):
                raise ValueError('Unknown or cross-world returned document')
            recomputed=retrieval_scores(predicted,case['relevant_ids'],m['k'])
            for key,value in recomputed.items():
                if metric[key]!=value: raise ValueError('Retrieval metric mismatch: '+key)
        elif task in ('conflict_rules','conflict_ai'):
            case=next(c for c in data['conflicts'] if c['id']==row['case_id'])
            peers={i for i in case['existing_ids'] if docs[i]['world']==case['draft']['world']}
            if task=='conflict_rules':
                gold={(e['spell_id'],e['kind']) for e in case['expected_rule_events']}
                pred={tuple(e) for e in row['returned']}; universe={(i,k) for i in peers for k in KINDS}
            else:
                gold=set(case['expected_ai_ids']); pred={e['spell_id'] for e in row['returned']}; universe=peers
            counts=classification_counts(pred,gold,universe)
            if counts!=row['counts']: raise ValueError('Confusion matrix mismatch')
            for key,value in {**classification_scores(counts),'exact_match':float(pred==gold)}.items():
                if metric[key]!=value: raise ValueError('Conflict metric mismatch: '+key)
        elif task=='generation':
            case=next(c for c in data['generation'] if c['id']==row['case_id'])
            recomputed=structural_quality(row['draft'],case['request'],docs.values())
            recomputed['contract_pass']=all(recomputed.values())
            for key,value in recomputed.items():
                if metric[key]!=value: raise ValueError('Generation contract mismatch: '+key)
            if m['judge_enabled'] and not row.get('judge'): raise ValueError('Missing judgment')
            if row.get('judge'):
                from eval.kharakteres_benchmark import RUBRIC
                from eval.benchmark_metrics import mean
                judge=row['judge']
                if len(judge['criteria'])!=len(case['criteria']) or any(type(x) is not bool for x in judge['criteria']):
                    raise ValueError('Invalid judge checklist')
                if any(type(judge[k]) is not int or not 0<=judge[k]<=4 for k in RUBRIC):
                    raise ValueError('Invalid rubric score')
                score=mean(judge[k] for k in RUBRIC)
                rate=mean(judge['criteria'])
                passed=all(judge[k]>=3 for k in RUBRIC) and all(judge['criteria'])
                if score!=judge['mean_score'] or score!=metric['judge_score'] or rate!=judge['criteria_rate'] or rate!=metric['judge_criteria_rate'] or passed!=judge['passed']:
                    raise ValueError('Judge aggregate mismatch')
    if summaries(report['rows'],m['repeat'])!=report['summary']:
        raise ValueError('Summary differs from raw evidence')
    if paired_comparisons(report['rows'],m['seed'])!=report['paired_comparisons']:
        raise ValueError('Paired bootstrap differs from raw evidence')
    return {'integrity':'passed','rows':len(actual),'dataset_sha256':m['dataset_sha256'],
            'quality_target':'not asserted; inspect measured precision/recall and failures separately'}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('report',type=Path)
    p.add_argument('--dataset',type=Path,default=ROOT/'eval/datasets/kharakteres_v1.json')
    args=p.parse_args()
    result=audit(json.loads(args.report.read_text()),args.dataset)
    output=args.report.parent/'audit.json'
    output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(result,ensure_ascii=False))


if __name__=='__main__': main()
