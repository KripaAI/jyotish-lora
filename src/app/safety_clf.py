"""A small learned screen that catches sensitive requests the keyword rules miss (paraphrases, mixed Hindi-English).

    python -m src.app.safety_clf cv      # 5-fold cross-validation on the dev sets (recall at a fixed wrong-block rate)
    python -m src.app.safety_clf train   # fit on all dev data -> src/app/safety_clf.joblib

Features: word and character n-gram TF-IDF. Model: logistic regression, one class per sensitive category plus 'normal'.
The question is blocked when P(normal) is below THRESHOLD; the predicted category chooses the fixed reply.
Trained only on data/dpo/safety/questions.jsonl (sensitive) and the v2 train split (normal): never on the evaluation sets.
"""
from __future__ import annotations

import sys
from pathlib import Path

import joblib
import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from scipy.optimize import minimize
from scipy.special import logsumexp
from sklearn.model_selection import StratifiedKFold
from sklearn.pipeline import FeatureUnion, Pipeline
from sklearn.base import BaseEstimator, ClassifierMixin

from src.app.safety_report import normal_dev, sensitive_dev

MODEL = Path(__file__).with_name("safety_clf.joblib")
THRESHOLD = 0.4      # block when P(normal) < THRESHOLD; chosen by cross-validation of rules + classifier together


class SoftmaxLR(BaseEstimator, ClassifierMixin):
    """Multinomial logistic regression (L2, balanced class weights) fitted with L-BFGS.

    Written with scipy because scikit-learn's own LogisticRegression imports a compiled file that this machine's
    Application Control policy blocks."""

    def __init__(self, C=8.0, max_iter=300):
        self.C, self.max_iter = C, max_iter

    def fit(self, X, y):
        self.classes_, yi = np.unique(y, return_inverse=True)
        n, d = X.shape
        k = len(self.classes_)
        w = (n / (k * np.bincount(yi)))[yi]                       # balanced class weights
        Y = np.zeros((n, k)); Y[np.arange(n), yi] = 1

        def loss(theta):
            W, b = theta[: d * k].reshape(d, k), theta[d * k:]
            Z = X @ W + b
            lse = logsumexp(Z, axis=1)
            P = np.exp(Z - lse[:, None])
            f = (w * (lse - Z[np.arange(n), yi])).sum() * self.C + 0.5 * (W ** 2).sum()
            G = (X.T @ ((P - Y) * w[:, None])) * self.C + W
            gb = ((P - Y) * w[:, None]).sum(0) * self.C
            return f, np.concatenate([np.asarray(G).ravel(), gb])

        res = minimize(loss, np.zeros(d * k + k), jac=True, method="L-BFGS-B", options={"maxiter": self.max_iter})
        self.W_, self.b_ = res.x[: d * k].reshape(d, k), res.x[d * k:]
        return self

    def predict_proba(self, X):
        Z = X @ self.W_ + self.b_
        Z = Z - Z.max(1, keepdims=True)
        P = np.exp(Z)
        return P / P.sum(1, keepdims=True)

    def predict(self, X):
        return self.classes_[self.predict_proba(X).argmax(1)]


def make() -> Pipeline:
    feats = FeatureUnion([
        ("word", TfidfVectorizer(ngram_range=(1, 2), min_df=2, sublinear_tf=True, lowercase=True)),
        ("char", TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5), min_df=3, sublinear_tf=True, lowercase=True)),
    ])
    return Pipeline([("f", feats), ("lr", SoftmaxLR(C=8.0))])


def data():
    sens, norm = sensitive_dev(), normal_dev()
    X = [t for t, _ in sens] + [t for t, _ in norm]
    y = [c for _, c in sens] + ["normal"] * len(norm)
    return X, np.array(y)


def p_normal(model, texts):
    proba = model.predict_proba(texts)
    return proba[:, list(model.classes_).index("normal")]


def cv() -> None:
    X, y = data()
    Xa = np.array(X, dtype=object)
    p_norm = np.zeros(len(y))
    for tr, te in StratifiedKFold(5, shuffle=True, random_state=0).split(Xa, y):
        m = make().fit(list(Xa[tr]), y[tr])
        p_norm[te] = p_normal(m, list(Xa[te]))
    sens = y != "normal"
    print(f"{sens.sum()} sensitive, {(~sens).sum()} normal")
    for thr in (0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9):
        block = p_norm < thr
        print(f"  threshold {thr}: recall {block[sens].mean():.1%}   wrongly blocked normal {block[~sens].mean():.1%}")


def train() -> None:
    X, y = data()
    m = make().fit(X, y)
    joblib.dump(m, MODEL)
    print("saved", MODEL, MODEL.stat().st_size // 1024, "KiB; classes:", list(m.classes_))


if __name__ == "__main__":
    {"cv": cv, "train": train}[sys.argv[1]]()
