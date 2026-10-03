"""Extract variant-linked PubMed IDs from a ClinVar citations TSV."""
import csv,json,sys
from genomics.core import DATA,local_records
ids={r['variation_id'] for r in local_records().values()}; citations={}
with open(sys.argv[1]) as f:
    for r in csv.DictReader(f,delimiter='\t'):
        if r['VariationID'] in ids and r['citation_source']=='PubMed': citations.setdefault(r['VariationID'],[]).append(r['citation_id'])
(DATA/'variant_citations.json').write_text(json.dumps({k:sorted(set(v),key=int) for k,v in citations.items()}))
print('Linked variant citation sets:',len(citations))
