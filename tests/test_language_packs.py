"""Shared concepts, adversarial multilingual cases and data-only language packs."""
import copy
import contextlib
import io
import json
import tempfile
import unicodedata
import unittest
from pathlib import Path
from unittest.mock import patch

import openpyxl
import yaml
import fond_analysis as f
from language_packs import LanguageRegistry, alias_hits, read_mapping, local_path
from text_matching import MATCH_LANGUAGE, item_matcher, stem_tokens

ROOT = Path(__file__).resolve().parents[1]
LANGUAGES = ('en', 'uk', 'hr', 'it')


class LanguagePackTests(unittest.TestCase):
    def setUp(self):
        self.saved = f.ANALYSIS_CONFIG, dict(f.LANGUAGE_CATEGORIES), dict(f.LANGUAGE_AMBIGUITIES)
        f.ANALYSIS_CONFIG = {'analysis': {'vocabulary_mode': 'aligned'}}
        f.LANGUAGE_CATEGORIES.clear()
        f.LANGUAGE_AMBIGUITIES.clear()
        self.packs = {}
        for code in LANGUAGES:
            cats, amb, self.blocks, version = f.load_dictionaries(yaml, code)
            self.packs[code] = cats, amb
            f.LANGUAGE_CATEGORIES[code] = cats
            f.LANGUAGE_AMBIGUITIES[code] = amb
        self.registry = LanguageRegistry.load()

    def tearDown(self):
        f.ANALYSIS_CONFIG, cats, amb = self.saved
        f.LANGUAGE_CATEGORIES.clear(); f.LANGUAGE_CATEGORIES.update(cats)
        f.LANGUAGE_AMBIGUITIES.clear(); f.LANGUAGE_AMBIGUITIES.update(amb)

    def result(self, title, code):
        return f.classify_title(title, *self.packs[code], list(self.blocks), code)

    def test_same_concepts_roles_anchors_and_versions(self):
        reference = {c['id']: c for c in self.registry.reference['concepts']}
        for code in LANGUAGES:
            cats, _ = self.packs[code]
            definitions = {c['id']: c for cat in cats for c in cat.concepts}
            self.assertEqual(set(definitions), set(reference))
            for cid, definition in definitions.items():
                for field in ('category', 'kind', 'udc_codes', 'udc_relation', 'scope_note'):
                    self.assertEqual(definition[field], reference[cid][field])
            self.assertEqual(f.load_dictionaries(yaml, code)[3], self.registry.reference['version'])
            self.assertEqual(self.registry.metadata(code)['alignment'], 'reference_concepts')

    def test_independently_authored_positive_and_negative_pairs(self):
        cases = yaml.safe_load((ROOT/'tests/fixtures/multilingual_cases.yaml').read_text())
        for case in cases:
            for code, title in case['titles'].items():
                with self.subTest(case=case['id'], language=code, title=title):
                    self.assertEqual(set(self.result(title, code)[0]), set(case['categories']))

    def test_repeated_aliases_do_not_inflate_scores(self):
        for code, title in [('en','tax taxes taxation'),('uk','податок податки оподаткування'),
                            ('hr','porez porezi oporezivanje'),('it','imposta imposte tassazione')]:
            self.assertEqual(self.result(title,code)[3], {'economy':3})

    def test_unicode_nfd_apostrophe_and_token_boundaries(self):
        for code,title,expected in [('hr','LIŠENJE SLOBODE',{'law_and_police'}),
                                   ('it','ATTIVITÀ CULTURALE',{'culture'}),
                                   ('it','Riparazione dell’ospedale',{'healthcare'})]:
            self.assertEqual(set(self.result(unicodedata.normalize('NFD',title),code)[0]),expected)
        self.assertFalse(self.result('schoolhouse taxationist', 'en')[0])
        self.assertFalse(self.result('zgrada', 'hr')[0])
        self.assertEqual(alias_hits('Corrispondenza', 'it', 'document_types'), {'correspondence':'Corrispondenza'})

    def test_legacy_ukrainian_can_be_reproduced_explicitly(self):
        old,amb,blocks,version=f.load_dictionaries(yaml,'uk',legacy=True)
        self.assertEqual(version,'0.8-draft')
        self.assertFalse(any(c.concepts for c in old))
        self.assertIn('education',f.classify_title('Арешт учителя',old,amb,list(blocks),'uk')[0])
        self.assertNotIn('education',self.result('Арешт учителя','uk')[0])
        with patch.object(f,'ANALYSIS_CONFIG',{'analysis':{'vocabulary_mode':'legacy_uk'}}):
            self.assertEqual(f.load_dictionaries(yaml)[3],'0.8-draft')
            self.assertEqual(f.analysis_languages().metadata('uk')['alignment'],'legacy_category_ids_only')

    def test_registry_rejects_unknown_missing_and_duplicate_data(self):
        index=yaml.safe_load((ROOT/'config/categories.yaml').read_text())
        for mutation in ('unknown','missing','version','duplicate','labels'):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp); (root/'config').mkdir(); (root/'dictionaries').mkdir()
                data=copy.deepcopy(self.registry.data)
                data['reference_file']='dictionaries/reference.yaml'
                for code in ('uk','hr','it'):
                    data['languages'][code]['terms_file']=f'dictionaries/{code}.yaml'
                    terms=yaml.safe_load((ROOT/f'dictionaries/{code}/terms.yaml').read_text())
                    if code=='hr':
                        if mutation=='unknown': terms['concepts']['invented_concept']=['x']
                        elif mutation=='missing': terms['concepts'].pop('education')
                        elif mutation=='version': terms['reference_version']='0'
                        elif mutation=='duplicate': terms['concepts']['education']=['obrazovanje','OBRAZOVANJE']
                        else: terms['preferred_labels'].pop('education')
                    (root/f'dictionaries/{code}.yaml').write_text(yaml.safe_dump(terms,allow_unicode=True))
                (root/'dictionaries/reference.yaml').write_text(yaml.safe_dump(self.registry.reference))
                path=root/'config/languages.yaml'; path.write_text(yaml.safe_dump(data))
                with self.assertRaises(ValueError): LanguageRegistry.load(path).compile('hr',index)

    def test_duplicate_yaml_keys_and_escaping_paths_are_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            path=root/'terms.yaml';path.write_text('language: hr\nlanguage: it\n')
            with self.assertRaisesRegex(ValueError,'Duplicate YAML key'):
                read_mapping(path)
            with self.assertRaisesRegex(ValueError,'inside the project'):
                local_path(root,'../outside.yaml')

    def test_foreign_auxiliary_lookups_do_not_use_english_fallback(self):
        self.assertFalse(alias_hits('burgher', 'it', 'terminology'))
        self.assertFalse(alias_hits('report', 'hr', 'document_types'))
        self.assertIn('censorship',alias_hits('Cenzura', 'hr', 'terminology'))

    def test_new_language_is_data_only(self):
        registry=copy.deepcopy(self.registry)
        registry.languages['xy']={**registry.languages['hr'],'terms_file':'dictionaries/hr/terms.yaml'}
        # A plugin requires its own language-tagged data, not a Python branch.
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); (root/'dictionaries').mkdir()
            terms=yaml.safe_load((ROOT/'dictionaries/hr/terms.yaml').read_text());terms['language']='xy'
            (root/'dictionaries/xy.yaml').write_text(yaml.safe_dump(terms))
            registry.root=root;registry.languages['xy']['terms_file']='dictionaries/xy.yaml'
            result,_=registry.compile('xy',yaml.safe_load((ROOT/'config/categories.yaml').read_text()))
            self.assertEqual(len(result),12)

    def test_explicit_sheet_language_wins_and_unknown_latin_abstains(self):
        saved=f.INPUT_FILE,f.SOURCE_CONFIG,f.SHEET_NAMES,f.HEADER_ROWS_BY_SHEET
        try:
            with tempfile.TemporaryDirectory() as tmp:
                for declared,expected in [('hr','hr'),('','undetermined')]:
                    book=openpyxl.Workbook();s=book.active;s.title='Inventory 1'
                    s.append(['Archive','Test',None,'Language' if declared else None,declared])
                    s.append(['Fond','1']);s.append(['Inventory','1'])
                    s.append(['No.','Title','Dates','Folios','Notes']);s.append(['1','Zgrada','1945'])
                    f.INPUT_FILE=Path(tmp)/'input.xlsx';book.save(f.INPUT_FILE);book.close()
                    f.ANALYSIS_CONFIG={'analysis':{'language':'it'}} if declared else {}
                    f.configure_workbook_sources(openpyxl)
                    records,_,_=f.read_records(openpyxl)
                    self.assertEqual(records[0].language,expected)
                    if declared: self.assertEqual(records[0].language_source,'sheet_declared')
                    with contextlib.redirect_stdout(io.StringIO()):f.classify_records(records,*self.packs['uk'],list(self.blocks))
                    self.assertFalse(records[0].categories)
                    if not declared:self.assertIn('unsupported_language: undetermined',records[0].review_flags)
        finally:f.INPUT_FILE,f.SOURCE_CONFIG,f.SHEET_NAMES,f.HEADER_ROWS_BY_SHEET=saved

if __name__=='__main__':unittest.main()
