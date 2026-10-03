"""VCF-safe matching, evidence retrieval, and explicit uncertainty.

GRCh38 only. No liftover, left-normalization, genotype interpretation, or
therapy selection. Exact alleles only; absence is not evidence of benignity.
"""
from __future__ import annotations
import config
import csv, json, re, time, threading
from pathlib import Path
from datetime import datetime, timezone
import requests

ROOT = Path(__file__).resolve().parent
DATA = ROOT / 'data'
CLINVAR = 'https://ftp.ncbi.nlm.nih.gov/pub/clinvar/vcf_GRCh38/clinvar_20260928.vcf.gz'
GNOMAD = 'https://gnomad.broadinstitute.org/api'
DISCLAIMER = 'Research prototype only. Not clinical validation, a diagnosis, or a therapy recommendation. Do not upload real patient data.'
_lock = threading.Lock()

def variant_id(chrom, pos, ref, alt):
    chrom = str(chrom).removeprefix('chr')
    if chrom not in [str(i) for i in range(1,23)] + ['X','Y','M','MT']:
        raise ValueError('Unsupported chromosome')
    if not str(pos).isdigit() or int(pos) < 1: raise ValueError('Position must be a positive integer')
    ref, alt = str(ref).upper(), str(alt).upper()
    if not re.fullmatch('[ACGT]+',ref) or not re.fullmatch('[ACGT]+',alt):
        raise ValueError('Only sequence alleles A/C/G/T are supported; symbolic variants are not')
    if ref == alt: raise ValueError('REF and ALT must differ')
    return f'{chrom}-{int(pos)}-{ref}-{alt}'

def parse_input(text, assembly='GRCh38', limit=20):
    if assembly != 'GRCh38': raise ValueError('Only GRCh38 is supported; no automatic liftover')
    if len(text)>200000: raise ValueError('Input exceeds 200 KB')
    output=[]
    for line in text.splitlines():
        line=line.strip()
        if not line: continue
        if line.startswith('##reference=') and any(x in line.lower() for x in ['grch37','hg19']):
            raise ValueError('VCF reference conflicts with GRCh38')
        if line.startswith('#'): continue
        if '\t' in line or ' ' in line:
            parts=line.split()
            if len(parts)<5: raise ValueError('VCF needs CHROM POS ID REF ALT columns')
            chrom,pos,_,ref,alts=parts[:5]
        else:
            parts=line.split('-')
            if len(parts)!=4: raise ValueError('Use CHROM-POS-REF-ALT or VCF')
            chrom,pos,ref,alts=parts
        for alt in alts.split(','):
            vid=variant_id(chrom,pos,ref,alt)
            if vid not in output: output.append(vid)
            if len(output)>limit: raise ValueError(f'Maximum {limit} variants per request')
    if not output: raise ValueError('No variants supplied')
    return output

def parse_record(line):
    cols=line.rstrip().split('\t')
    chrom,pos,cvid,ref,alt=cols[:5]
    if ',' in alt: return None
    try: vid=variant_id(chrom,pos,ref,alt)
    except ValueError: return None
    info=dict(x.split('=',1) for x in cols[7].split(';') if '=' in x)
    return dict(variant_id=vid, variation_id=cvid, gene=info.get('GENEINFO','').split(':')[0],
        significance=info.get('CLNSIG','not_provided'), review_status=info.get('CLNREVSTAT','not_provided'),
        condition=info.get('CLNDN','not_provided'), consequence=info.get('MC','unknown'),
        source_url=f'https://www.ncbi.nlm.nih.gov/clinvar/variation/{cvid}/',
        snapshot='2026-09-28', assembly='GRCh38')

def local_records():
    with (DATA/'clinvar_sample.jsonl').open() as f:
        return {r['variant_id']:r for r in map(json.loads,f)}

_records=None

def clinvar_lookup(vid):
    global _records
    if _records is None: _records=local_records()
    if vid in _records: return {'status':'found_snapshot','record':_records[vid]}
    chrom,pos,ref,alt=vid.split('-'); pos=int(pos)
    try:
        import pysam
        with _lock, pysam.TabixFile(CLINVAR) as tb:
            candidates=[parse_record(s) for s in tb.fetch(chrom,pos-1,pos)]
        matches=[s for s in candidates if s and s['variant_id']==vid]
        if matches: return {'status':'found_remote_snapshot','record':matches[0]}
        return {'status':'not_found','source_url':CLINVAR,'note':'Exact allele absent in this snapshot. Not evidence of benignity; normalize indels against a reference before retrying.'}
    except Exception as e:
        return {'status':'unavailable','source_url':CLINVAR,'error':f'{type(e).__name__}: {e}'[:250]}

def gnomad_lookup(vid):
    cache=DATA/'gnomad_cache.json'
    with _lock:
        values=json.loads(cache.read_text()) if cache.exists() else {}
        if vid in values: return {**values[vid], 'cached':True}
        query='query($id:String!){variant(variantId:$id,dataset:gnomad_r4){variant_id exome{ac an af} genome{ac an af}}}'
        for attempt in range(2):
            try:
                time.sleep(.4)
                res=requests.post(GNOMAD,json={'query':query,'variables':{'id':vid}},timeout=25)
                res.raise_for_status(); body=res.json(); data=body.get('data',{}).get('variant')
                errors=body.get('errors',[])
                if errors and not all('Variant not found' in x.get('message','') for x in errors):
                    raise ValueError(str(errors)[:200])
                result={'status':'found' if data else 'not_found', 'dataset':'gnomad_r4', 'assembly':'GRCh38',
                        'data':data,'retrieved_at':datetime.now(timezone.utc).isoformat(), 'source_url':GNOMAD,
                        'note':'Exome and genome frequencies are separate. Absence does not prove pathogenicity.'}
                values[vid]=result; cache.write_text(json.dumps(values,indent=2)); return result
            except (requests.RequestException,ValueError) as e:
                if attempt==1: return {'status':'unavailable','source_url':GNOMAD,'error':str(e)[:250]}
                time.sleep(1)

def features(record):
    """Only sequence and consequence. NO labels, disease, review, IDs, or gene."""
    _,_,ref,alt=record['variant_id'].split('-')
    out={'ref_len':len(ref),'alt_len':len(alt),'length_delta':len(alt)-len(ref),
         'ref_gc':sum(b in 'GC' for b in ref)/len(ref),
         'alt_gc':sum(b in 'GC' for b in alt)/len(alt),
         'snv':int(len(ref)==len(alt)==1),
         'transition':int((ref,alt) in [('A','G'),('G','A'),('C','T'),('T','C')])}
    for term in record.get('consequence','unknown').split(','):
        out['consequence_'+term.split('|')[-1]]=1
    return out

def predict(record):
    if not record: return {'status':'abstained','reason':'No consequence annotation available'}
    if record['review_status'] not in ['reviewed_by_expert_panel','practice_guideline','criteria_provided,_multiple_submitters,_no_conflicts']:
        return {'status':'abstained','reason':'Outside curated training review-status scope'}
    if not any('consequence_'+t.split('|')[-1] in json.loads((DATA/'feature_names.json').read_text()) for t in record['consequence'].split(',')):
        return {'status':'abstained','reason':'Unseen molecular consequence'}
    import joblib
    model=joblib.load(DATA/'model.joblib')
    score=float(model.predict_proba([features(record)])[0,1])
    return {'status':'research_prediction','predicted_label':'pathogenic/likely pathogenic' if score>=.5 else 'benign/likely benign',
            'pathogenic_score':round(score,4),'note':'Model score is not calibrated clinical probability. Annotation features are not independent clinical evidence.',
            'agrees_with_clinvar': (score>=.5)==(record.get('label', 1 if record['significance'] in ['Pathogenic','Likely_pathogenic','Pathogenic/Likely_pathogenic'] else 0)),
            'seen_during_training': record['variation_id'] in json.loads((DATA/'split.json').read_text())['train_variation_ids']}

def interpret(text, assembly='GRCh38', literature=True):
    results=[]
    for vid in parse_input(text,assembly):
        cv=clinvar_lookup(vid); rec=cv.get('record'); gn=gnomad_lookup(vid)
        papers=[]; lit={'status':'disabled'}
        if literature and rec and rec['gene']:
            try:
                from tools.pubmed_tool import search_pubmed
                ids=json.loads((DATA/'variant_citations.json').read_text()).get(rec['variation_id'],[])[:3]
                query=' OR '.join(f'{i}[uid]' for i in ids) if ids else f"{rec['gene']} variant"
                papers=[p.to_dict() for p in search_pubmed(query,3)]
                lit={'status':'found' if papers else 'no_results','query':query,'scope':'ClinVar-linked variant citations (not proof of therapy efficacy)' if ids else 'Gene-level search, not necessarily evidence about this exact allele'}
            except Exception as e: lit={'status':'unavailable','error':str(e)[:250]}
        pred=predict(rec)
        if rec:
            cv={**cv,'record':{k:v for k,v in rec.items() if k!='label'}}
        summary=(f"{vid} (GRCh38). ClinVar snapshot classification: {rec['significance'].replace('_',' ')}; "
                 f"review: {rec['review_status'].replace('_',' ')}; condition: {rec['condition'].replace('_',' ')}. " if rec else f'{vid}: no verified ClinVar match. ')
        summary+=f"gnomAD: {gn['status']}. Population rarity alone does not establish pathogenicity. "
        if pred.get('agrees_with_clinvar') is False: summary+='The experimental model conflicts with ClinVar; do not use its prediction as clinical evidence. '
        summary+='No patient phenotype, inheritance, zygosity, or validated treatment evidence assessed. No therapy recommendation.'
        results.append({'variant_id':vid,'clinvar':cv,'gnomad':gn,'classifier':pred,'literature':lit,'papers':papers,'summary':summary})
    return {'disclaimer':DISCLAIMER,'assembly':assembly,'results':results}
