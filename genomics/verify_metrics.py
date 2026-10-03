"""Independently recompute the shipped accuracy from exported predictions."""
import csv,json
from genomics.core import DATA
from sklearn.metrics import accuracy_score, balanced_accuracy_score, roc_auc_score
rows=list(csv.DictReader((DATA/'test_predictions.csv').open()))
y=[int(r['true_label']) for r in rows];p=[int(r['predicted_label']) for r in rows];s=[float(r['pathogenic_score']) for r in rows]
m=json.loads((DATA/'metrics.json').read_text())
for key,value in [('accuracy',accuracy_score(y,p)),('balanced_accuracy',balanced_accuracy_score(y,p)),('roc_auc',roc_auc_score(y,s))]:
    assert abs(m[key]-value)<1e-12;print(key,value)
print('Exported predictions match stored test metrics exactly')
