"""Build a balanced research sample from a COMPLETE ClinVar VCF scan.
Reservoir sampling, deduplicated Variation IDs, reproducible seed. Nothing synthetic.
"""
import gzip, json, random, sys, hashlib
from collections import Counter
from pathlib import Path
from genomics.core import DATA, CLINVAR, parse_record

def build(path,per_class=20000):
    DATA.mkdir(exist_ok=True); rng=random.Random(42)
    reservoirs={0:[],1:[]}; counts=Counter(); seen=set(); scanned=0
    labels={'Benign':0,'Likely_benign':0,'Benign/Likely_benign':0,
            'Pathogenic':1,'Likely_pathogenic':1,'Pathogenic/Likely_pathogenic':1}
    reviews={'reviewed_by_expert_panel','practice_guideline','criteria_provided,_multiple_submitters,_no_conflicts'}
    with gzip.open(path,'rt') as f:
        for line in f:
            if line.startswith('#'): continue
            scanned+=1; r=parse_record(line)
            if not r or r['variation_id'] in seen or not r['gene'] or '|' in r['gene']: continue
            if r['significance'] not in labels or r['review_status'] not in reviews or r['consequence']=='unknown': continue
            seen.add(r['variation_id']); y=labels[r['significance']]; r['label']=y; counts[y]+=1
            if len(reservoirs[y])<per_class: reservoirs[y].append(r)
            else:
                index=rng.randrange(counts[y])
                if index<per_class: reservoirs[y][index]=r
    rows=reservoirs[0]+reservoirs[1]; rng.shuffle(rows)
    out=DATA/'clinvar_sample.jsonl'
    out.write_text(''.join(json.dumps(r)+'\n' for r in rows))
    manifest={'source_url':CLINVAR,'snapshot':'2026-09-28','assembly':'GRCh38','seed':42,
       'scanned_vcf_records':scanned,'eligible_by_class':dict(counts),'sample_by_class':{k:len(v) for k,v in reservoirs.items()},
       'sha256_sample':hashlib.sha256(out.read_bytes()).hexdigest(),
       'selection':'Whole-file per-class reservoir sample; no uncertain/conflicting labels; >=2-star germline review; sequence alleles, one gene, known consequence'}
    (DATA/'manifest.json').write_text(json.dumps(manifest,indent=2)); print(json.dumps(manifest,indent=2))
if __name__=='__main__': build(sys.argv[1])
