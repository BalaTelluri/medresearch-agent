import argparse
import json
from pharmacovigilance.core import build_report
p = argparse.ArgumentParser(description='Exploratory FAERS evidence, not clinical advice')
p.add_argument('drug')
p.add_argument('--offline', action='store_true')
p.add_argument('--json', action='store_true')
a = p.parse_args()
r = build_report(a.drug, live=not a.offline)
print(json.dumps(r, indent=2) if a.json else r.get('report_markdown', r.get('error')))
