#!/usr/bin/env python3

from typing import NamedTuple, Type

import gpytorch
import torch
from botorch.fit import fit_model
from gpytorch.likelihoods import GaussianLikelihood
from gpytorch.models import ExactGP
from torch import Tensor
from torch.distributions import Distribution


class CVFolds(NamedTuple):
    train_x: Tensor
    train_y: Tensor
    test_x: Tensor
    test_y: Tensor


class CVResults(NamedTuple):
    posterior: Distribution
    observed: Tensor


def gen_loo_cv_folds(train_x: Tensor, train_y: Tensor) -> CVFolds:
    """Generate LOO CV folds

    Args:
        train_x: An `n x p` tensor
        train_y: An `n` or `n x t` tensor (the latter n the multi-output case,
            where `t` the number of outputs)

    Returns:
        CVFolds tuple with the following fields:
            train_x: A `n x (n-1) x p` tensor of training features
            train_y: A `n x (n-1)` (or `n x (n-1) x t`) tensor of traiing observations
            test_x: A `n x 1 x p` tensor of test features
            test_y: A `n` or `n x t` tensor of test observations

    """
    masks = torch.eye(len(train_x), dtype=torch.uint8, device=train_x.device)
    train_x_cv = torch.cat([train_x[~m].unsqueeze(0) for m in masks])
    train_y_cv = torch.cat([train_y[~m].unsqueeze(0) for m in masks])
    test_x_cv = torch.cat([train_x[m].unsqueeze(0) for m in masks])
    test_y_cv = torch.cat([train_y[m].unsqueeze(0) for m in masks])
    return CVFolds(
        train_x=train_x_cv, train_y=train_y_cv, test_x=test_x_cv, test_y=test_y_cv
    )


def batch_cross_validation(
    model_cls: Type[ExactGP],
    likelihood_cls: Type[GaussianLikelihood],
    cv_folds: CVFolds,
) -> CVResults:
    """Perform cross validation by using gpytorch batch mode

    Args:
        model_cls: An ExactGP class. Must be able to work both in non-batch and
            in batch mode, and take a "batch_size" kwarg in its constructor
        likelihood_cls: A GaussianLikelihood class. Must be able to work both in
            non-batch and in batch mode, and take a "batch_size" kwarg in its
            constructor
        cv_folds: A CVFolds tuple

    Returns:
        A CVResults tuple with the following fields:
            - posterior: A batched torch Distribution, each batch representing
                the posteriors of the model on the assocoated test point(s).
            - observations: A `n` or `n x t` tensor of test observations

    WARNING: This function is currently very memory inefficient, use it only
        for problems of small size.

    """
    num_folds = cv_folds.train_x.shape[0]
    likelihood_cv = likelihood_cls(batch_size=num_folds)
    # Fit the model in batch mode (needs to be improved)
    model_cv = fit_model(
        gp_model=model_cls,
        likelihood=likelihood_cv,
        train_x=cv_folds.train_x,
        train_y=cv_folds.train_y,
        model_kwargs={"batch_size": num_folds},
        verbose=False,
    )
    # Evaluate on the hold-out set in batch mode
    with torch.no_grad(), gpytorch.fast_pred_var():
        posterior = likelihood_cv(model_cv(cv_folds.test_x))

    return CVResults(posterior=posterior, observed=cv_folds.test_y)