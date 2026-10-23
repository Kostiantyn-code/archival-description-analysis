#!/usr/bin/env python3
"""Check shared vocabulary and optionally regenerate a reviewable crosswalk.

Run from any directory: python tools/validate_language_packs.py [--write]
This is a structural/development check, not an estimate of corpus accuracy.
"""
from __future__ import annotations
import argparse
import csv
import hashlib
import io
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import yaml
from language_packs import LanguageRegistry
import fond_analysis as f


def evaluate():
    registry = LanguageRegistry.load()
    index = yaml.safe_load((ROOT / 'config/categories.yaml').read_text())
    languages = [code for code, pack in registry.languages.items() if pack['vocabulary']=='reference']
    ordered = ['en', *sorted(code for code in languages if code != 'en')]
    aliases = {}
    labels = {}
    for code in ordered:
        _, content = registry.compile(code, index)
        aliases[code] = {c['id']:c['terms'] for c in content['concepts']} if code=='en' else content['concepts']
        labels[code] = {c['id']:c['label_en'] for c in content['concepts']} if code=='en' else content['preferred_labels']
    columns = ['concept_id','category','role','udc_codes','udc_relation','scope_note',
               *[f'label_{c}' for c in ordered], *[f'terms_{c}' for c in ordered]]
    stream=io.StringIO(newline='')
    writer=csv.DictWriter(stream,fieldnames=columns,lineterminator='\n')
    writer.writeheader()
    for concept in registry.reference['concepts']:
        cid=concept['id']
        writer.writerow({'concept_id':cid,'category':concept['category'],'role':concept['kind'],
                         'udc_codes':' | '.join(concept['udc_codes']),'udc_relation':concept['udc_relation'],
                         'scope_note':concept['scope_note'],
                         **{f'label_{c}':labels[c][cid] for c in ordered},
                         **{f'terms_{c}':' | '.join(aliases[c][cid]) for c in ordered}})
    # Load production dictionaries and exercise separately authored contrast cases.
    f.ANALYSIS_CONFIG={'analysis':{'vocabulary_mode':'aligned'}}
    f.LANGUAGE_CATEGORIES.clear();f.LANGUAGE_AMBIGUITIES.clear()
    for code in ordered:
        cats,amb,blocks,_=f.load_dictionaries(yaml,code)
        f.LANGUAGE_CATEGORIES[code]=cats;f.LANGUAGE_AMBIGUITIES[code]=amb
    cases=yaml.safe_load((ROOT/'tests/fixtures/multilingual_cases.yaml').read_text())
    failures=[]
    for case in cases:
        for code,title in case['titles'].items():
            result=f.classify_title(title,f.LANGUAGE_CATEGORIES[code],f.LANGUAGE_AMBIGUITIES[code],list(blocks),code)
            if set(result[0])!=set(case['categories']):
                failures.append({'case':case['id'],'language':code,'expected':case['categories'],'actual':result[0]})
    inputs=[ROOT/'config/languages.yaml',ROOT/'config/categories.yaml',*registry.source_paths(),
            ROOT/'tests/fixtures/multilingual_cases.yaml',ROOT/'language_packs.py',ROOT/'fond_analysis.py',ROOT/'text_matching.py']
    manifest={'reference_version':registry.reference['version'], 'concept_count':len(registry.reference['concepts']),
              'rule_count':len(registry.reference['rules']), 'aligned_languages':ordered,
              'concepts_without_udc':[c['id'] for c in registry.reference['concepts'] if not c['udc_codes']],
              'synthetic_case_sets':len(cases),'synthetic_language_cases':sum(len(c['titles']) for c in cases),
              'failures':failures,'status':'passed' if not failures else 'failed',
              'validation_scope':'Structural checks and developer-authored synthetic contrasts; no independent linguistic or corpus accuracy validation.',
              'sha256':{str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(set(inputs))}}
    return stream.getvalue(),manifest


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--write',action='store_true',help='Regenerate docs/vocabulary_alignment.csv and docs/vocabulary_checks.json')
    args=parser.parse_args()
    crosswalk,manifest=evaluate()
    if args.write:
        (ROOT/'docs/vocabulary_alignment.csv').write_text(crosswalk,encoding='utf-8')
        (ROOT/'docs/vocabulary_checks.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({k:v for k,v in manifest.items() if k!='sha256'},ensure_ascii=False,indent=2))
    return bool(manifest['failures'])

if __name__=='__main__':raise SystemExit(main())
