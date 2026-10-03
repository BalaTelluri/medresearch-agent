import json, unittest
from unittest.mock import patch
from pathlib import Path
from fastapi.testclient import TestClient
from serve.api import app
from genomics.core import parse_input, features, local_records, interpret, clinvar_lookup, DATA
class GenomicsTests(unittest.TestCase):
 def test_ids(self): self.assertEqual(parse_input('chr13-32380145-g-t'),['13-32380145-G-T'])
 def test_vcf(self): self.assertEqual(parse_input('1\t10\t.\tA\tC,G\t.\tPASS\t.'),['1-10-A-C','1-10-A-G'])
 def test_dedup(self): self.assertEqual(parse_input('1-10-A-C\n1-10-A-C'),['1-10-A-C'])
 def test_reject(self):
  for text in ['','BRCA2','1-0-A-C','1-10-A-<DEL>','25-10-A-C','1-10-A-A','1-10-N-C']:
   with self.assertRaises(ValueError): parse_input(text)
 def test_limits(self):
  with self.assertRaises(ValueError): parse_input('\n'.join(f'1-{i}-A-C' for i in range(1,22)))
  with self.assertRaises(ValueError): parse_input('a'*200001)
 def test_assembly(self):
  with self.assertRaises(ValueError): parse_input('1-1-A-C','GRCh37')
  with self.assertRaises(ValueError): parse_input('##reference=hg19\n1-1-A-C')
 def test_feature_leakage(self):
  a=next(iter(local_records().values())); b={**a,'label':1-a['label'],'significance':'fake','gene':'fake','condition':'fake','review_status':'fake','variation_id':'fake'}
  self.assertEqual(features(a),features(b))
 def test_sample_hash(self):
  import hashlib
  self.assertEqual(hashlib.sha256((DATA/'clinvar_sample.jsonl').read_bytes()).hexdigest(),json.loads((DATA/'manifest.json').read_text())['sha256_sample'])
 def test_split(self):
  sp=json.loads((DATA/'split.json').read_text());rows={r['variation_id']:r for r in local_records().values()}
  self.assertFalse(set(sp['train_variation_ids']) & set(sp['test_variation_ids']))
  self.assertFalse({rows[i]['gene'] for i in sp['train_variation_ids']} & {rows[i]['gene'] for i in sp['test_variation_ids']})
 def test_no_therapy(self):
  with patch('genomics.core.gnomad_lookup',return_value={'status':'unavailable','error':'test'}):
   r=interpret('13-32380145-G-T',literature=False)
   self.assertIn('No therapy recommendation',r['results'][0]['summary'])
   self.assertNotIn('label',r['results'][0]['clinvar']['record'])
 def test_api(self):
  c=TestClient(app)
  self.assertEqual(c.get('/api/health').status_code,200)
  self.assertEqual(c.get('/genomics').status_code,200)
  self.assertEqual(c.get('/api/genomics/metrics').json()['metrics']['test_variants'],8834)
  self.assertEqual(c.post('/api/genomics/interpret',json={'text':'bad'}).status_code,400)
  with patch('genomics.core.gnomad_lookup',return_value={'status':'unavailable','error':'test'}):
   self.assertEqual(c.post('/api/genomics/interpret',json={'text':'13-32380145-G-T','literature':False}).status_code,200)
 def test_nested_sources(self):
  from agent.graph import _collect_sources
  self.assertEqual(_collect_sources({'nested':{'results':[{'source_url':'https://example.com/x'}]}}),['https://example.com/x'])
if __name__=='__main__':unittest.main()
