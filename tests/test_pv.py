import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from fastapi.testclient import TestClient
from serve.api import app
from pharmacovigilance import core

class PVTests(unittest.TestCase):
    def test_measured_corpus(self):
        r=core.snapshot('metformin')
        self.assertEqual((r['corpus_report_count'],r['corpus_reaction_rows']),(14914,69066))
        self.assertEqual(r['report_count'],3000)
        self.assertEqual(r['top_reactions'][0],{'reaction':'NAUSEA','report_count':199})
        self.assertEqual(sum(x['report_count'] for x in r['monthly_counts'])+r['missing_date_reports'],3000)
    def test_no_fuzzy_or_injection(self):
        self.assertIn('error',core.snapshot('met'))
        for x in ['', 'a', "metformin';DROP TABLE faers_reports", 'metformin OR 1=1']:
            with self.assertRaises(ValueError):core.snapshot(x)
    def test_snapshot_immutable(self):
        import hashlib
        p=core.ROOT/'data/faers_real.db';before=hashlib.sha256(p.read_bytes()).hexdigest()
        core.snapshot('metformin');self.assertEqual(before,hashlib.sha256(p.read_bytes()).hexdigest())
    def test_missing_db_no_demo(self):
        self.assertIn('error',core.snapshot('metformin',Path('/tmp/nonexistent-pv.db')))
    def test_no_invalid_prr(self):
        self.assertEqual(core.snapshot('metformin')['disproportionality']['status'],'not_computed')
    def test_comeds_not_invented(self):
        self.assertEqual(core.snapshot('metformin')['co_reported_drugs']['status'],'unavailable')
    def test_label_match_boundaries(self):
        b={'status':'retrieved','labels':[{'set_id':'x','effective_time':'20260101','sections':{'adverse_reactions':'nausea and diarrhea; abdominal pain'},'source_url':'https://example.org'}]}
        self.assertEqual(core.label_check('NAUSEA',b)['status'],'mentioned_in_retrieved_safety_sections')
        self.assertEqual(core.label_check('DIARRHOEA',b)['status'],'mentioned_in_retrieved_safety_sections')
        self.assertEqual(core.label_check('PAIN UPPER',b)['status'],'not_found_by_lexical_check')
    def test_label_unavailable_not_unlabeled(self):
        self.assertEqual(core.label_check('NAUSEA',{'status':'unavailable'})['status'],'unavailable')
    def test_offline_no_external_calls(self):
        with patch.object(core,'retrieve_labels',side_effect=AssertionError('network')),patch.object(core.pubmed_tool,'search_pubmed',side_effect=AssertionError('network')):
            r=core.build_report('metformin',False)
        self.assertTrue(r['gaps']);self.assertIn('NOT confirmed unlabeled',r['report_markdown'])
    def test_external_failures_preserve_counts(self):
        with patch.object(core,'retrieve_labels',side_effect=RuntimeError('offline')),patch.object(core.pubmed_tool,'search_pubmed',side_effect=ValueError('missing email')),patch.object(core.time,'sleep'):
            r=core.build_report('metformin')
        self.assertEqual(r['report_count'],3000);self.assertEqual(len(r['gaps']),5)
        self.assertEqual(r['top_reactions'][0]['label_check']['status'],'unavailable')
    def test_api(self):
        c=TestClient(app)
        self.assertEqual(c.get('/pharmacovigilance').status_code,200)
        self.assertEqual(len(c.get('/api/pv/drugs').json()),6)
        self.assertEqual(c.post('/api/pv/report',json={'drug':'metformin','live':False}).status_code,200)
        self.assertEqual(c.post('/api/pv/report',json={'drug':'unknown','live':False}).status_code,404)
        self.assertEqual(c.post('/api/pv/report',json={'drug':"a'",'live':False}).status_code,422)
    def test_graph_full_no_key(self):
        from agent import graph
        from tools import registry
        r=core.build_report('metformin',False)
        with patch.dict(registry.TOOLS,{'pharmacovigilance_report':(lambda q:r,'test')}),patch.object(graph.llm_client,'complete',side_effect=AssertionError('LLM must not be called')):
            s=graph.run('pharmacovigilance metformin')
            self.assertEqual(s['answer'],r['report_markdown']);self.assertTrue(s['sources'])
            c=TestClient(app);resp=c.post('/api/ask',json={'question':'safety signal metformin'})
            self.assertEqual(resp.status_code,200)
            self.assertIn('pharmacovigilance_report',resp.json()['tools_used'])
            resp=c.post('/api/ask/stream',json={'question':'pharmacovigilance metformin'})
            events=[json.loads(x) for x in resp.text.splitlines()]
            self.assertEqual(events[-1]['type'],'done');self.assertEqual(events[-1]['answer'],r['report_markdown'])
    def test_generic_registry_planner_router_citations(self):
        from agent import graph
        with patch.object(graph.llm_client,'complete',return_value='[{"tool":"interpret_genomic_variants","query":"13-32380145-G-T"}]'):
            s=graph.planner({'question':'Interpret 13-32380145-G-T'})
        self.assertEqual(s['plan'][0]['tool'],'interpret_genomic_variants')
        from tools import registry
        with patch.dict(registry.TOOLS,{'interpret_genomic_variants':(lambda q:{'nested':[{'source_url':'https://example.org/evidence'}]},'test')}):
            routed=graph.tool_router(s)
        self.assertEqual(graph._collect_sources(routed['tool_results']),['https://example.org/evidence'])

    def test_existing_genomics_graph_complete_mocked(self):
        from agent import graph
        from tools import registry
        evidence={'nested':[{'source_url':'https://example.org/evidence'}]}
        with patch.dict(registry.TOOLS,{'interpret_genomic_variants':(lambda q:evidence,'test')}),patch.object(graph.llm_client,'complete',side_effect=['[{"tool":"interpret_genomic_variants","query":"13-32380145-G-T"}]','Mock answer with source and research limits']):
            r=graph.run('Interpret 13-32380145-G-T')
        self.assertEqual(r['sources'],['https://example.org/evidence'])
        self.assertIn('answer: composed',r['trace'][-1])

if __name__=='__main__':unittest.main()
