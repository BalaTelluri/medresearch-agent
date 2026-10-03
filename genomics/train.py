"""Fixed random forest baseline; held-out genes, no tuning on test sample."""
import json, math
import joblib, numpy as np
from sklearn.pipeline import make_pipeline
from sklearn.feature_extraction import DictVectorizer
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import GroupShuffleSplit
from sklearn.metrics import accuracy_score, balanced_accuracy_score, f1_score, precision_score, recall_score, roc_auc_score, confusion_matrix
from genomics.core import DATA, local_records, features

def train():
    rows=list(local_records().values()); groups=np.array([r['gene'] for r in rows]); y=np.array([r['label'] for r in rows])
    train_idx,test_idx=next(GroupShuffleSplit(n_splits=1,test_size=.2,random_state=42).split(rows,y,groups))
    assert not set(groups[train_idx]) & set(groups[test_idx])
    assert not {rows[i]['variation_id'] for i in train_idx} & {rows[i]['variation_id'] for i in test_idx}
    model=make_pipeline(DictVectorizer(sparse=False),RandomForestClassifier(n_estimators=200,max_depth=12,min_samples_leaf=10,class_weight='balanced',random_state=42,n_jobs=2))
    model.fit([features(rows[i]) for i in train_idx],y[train_idx])
    pred=model.predict([features(rows[i]) for i in test_idx]); prob=model.predict_proba([features(rows[i]) for i in test_idx])[:,1]
    truth=y[test_idx]; n=len(truth); acc=accuracy_score(truth,pred)
    z=1.96; center=(acc+z*z/(2*n))/(1+z*z/n); radius=z*math.sqrt(acc*(1-acc)/n+z*z/(4*n*n))/(1+z*z/n)
    metrics={'evaluation':'held-out-gene test sample, NOT clinical validation','seed':42,'train_variants':len(train_idx),'test_variants':n,
      'train_genes':len(set(groups[train_idx])),'test_genes':len(set(groups[test_idx])),'gene_overlap':0,'variation_id_overlap':0,
      'accuracy':acc,'balanced_accuracy':balanced_accuracy_score(truth,pred),'pathogenic_precision':precision_score(truth,pred),
      'pathogenic_recall':recall_score(truth,pred),'pathogenic_f1':f1_score(truth,pred),'roc_auc':roc_auc_score(truth,prob),
      'confusion_matrix_true_rows_pred_columns_0_benign_1_pathogenic':confusion_matrix(truth,pred).tolist(),
      'accuracy_wilson_95_ci_variant_level_not_gene_clustered':[center-radius,center+radius],
      'majority_class_test_accuracy':float(max(np.mean(truth),1-np.mean(truth))),
      'test_class_counts':{'benign':int(sum(truth==0)),'pathogenic':int(sum(truth==1))},
      'limitations':['Balanced sample, not natural prevalence','Known ClinVar variants only; ascertainment bias','Sequence/consequence features only, no functional assays','No external cohort, prospective evaluation, or clinical validation','Scores uncalibrated; not patient risk','Gene holdout limits one leakage path but not all biological dependence']}
    joblib.dump(model,DATA/'model.joblib',compress=3)
    (DATA/'feature_names.json').write_text(json.dumps(list(model[0].get_feature_names_out())))
    (DATA/'metrics.json').write_text(json.dumps(metrics,indent=2))
    (DATA/'split.json').write_text(json.dumps({'train_variation_ids':[rows[i]['variation_id'] for i in train_idx], 'test_variation_ids':[rows[i]['variation_id'] for i in test_idx]}))
    with (DATA/'test_predictions.csv').open('w') as f:
        f.write('variation_id,gene,true_label,predicted_label,pathogenic_score\n')
        for i,p,s in zip(test_idx,pred,prob): f.write(f"{rows[i]['variation_id']},{rows[i]['gene']},{rows[i]['label']},{p},{s}\n")
    print(json.dumps(metrics,indent=2))
if __name__=='__main__': train()
