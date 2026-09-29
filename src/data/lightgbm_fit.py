"""Fit identical LightGBM settings with or without its scikit-learn wrapper."""

import lightgbm as lgb
import numpy as np
import pandas as pd


def fit_predict(x_train, y_train, x_test, names, settings):
    if lgb.compat.SKLEARN_INSTALLED:
        model = lgb.LGBMRegressor(**settings)
        model.fit(pd.DataFrame(x_train, columns=names), y_train)
        predicted = model.predict(pd.DataFrame(x_test, columns=names))
    else:
        # A Windows policy can block a scikit-learn DLL while LightGBM's
        # native training library remains available. The parameters match.
        parameters = {
            "objective": settings["objective"],
            "learning_rate": settings["learning_rate"],
            "num_leaves": settings["num_leaves"],
            "min_data_in_leaf": settings["min_child_samples"],
            "seed": settings["random_state"],
            "num_threads": settings["n_jobs"],
            "verbosity": settings["verbosity"],
        }
        training = lgb.Dataset(x_train, label=y_train, feature_name=list(names))
        model = lgb.train(parameters, training, num_boost_round=settings["n_estimators"])
        predicted = model.predict(x_test)
    return np.maximum(0, predicted)
