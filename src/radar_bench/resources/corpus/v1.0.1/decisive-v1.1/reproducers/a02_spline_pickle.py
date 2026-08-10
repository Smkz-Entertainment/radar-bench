"""Reproduce the scikit-learn #30512 SciPy-side pickle failure."""

from sklearn.preprocessing import SplineTransformer
from sklearn.utils.estimator_checks import check_estimators_pickle


check_estimators_pickle(
    name="hello",
    estimator_orig=SplineTransformer(),
    readonly_memmap=True,
)
