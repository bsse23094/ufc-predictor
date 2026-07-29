from __future__ import annotations

import optuna

from ufc_predictor.training.m4_optuna_tuning import (
    OPTUNA_SAMPLER_SEED,
    TRIAL_COUNT,
    TrialAggregate,
    _suggest_params,
    select_best_trial,
)


def _trial(number: int, loss: float, fold_losses: dict[str, float]) -> TrialAggregate:
    return TrialAggregate(
        number=number,
        params={"max_depth": 2, "min_child_weight": 8, "learning_rate": 0.04},
        mean_log_loss=loss,
        std_log_loss=0.01,
        mean_brier_score=0.24,
        mean_roc_auc=0.62,
        worst_fold_log_loss=loss + 0.01,
        mean_ece=0.02,
        mean_symmetric_complement_error=0.0,
        best_iteration_counts=[100, 110, 120],
        improvement_fold_count=0,
        fold_losses=fold_losses,
    )


def test_sampler_seed_and_bounds_are_deterministic() -> None:
    def sample() -> list[dict[str, float | int]]:
        study = optuna.create_study(
            directions=["minimize", "minimize", "minimize", "maximize", "minimize"],
            sampler=optuna.samplers.NSGAIISampler(seed=OPTUNA_SAMPLER_SEED),
        )
        output = []
        for _ in range(TRIAL_COUNT):
            trial = study.ask()
            params = _suggest_params(trial)
            study.tell(trial, (0.7, 0.01, 0.24, 0.62, float(params["max_depth"])))
            output.append(params)
        return output

    first, second = sample(), sample()
    assert first == second
    assert len(first) == TRIAL_COUNT
    for params in first:
        assert 1 <= params["max_depth"] <= 4
        assert 3 <= params["min_child_weight"] <= 16
        assert 0.015 <= params["learning_rate"] <= 0.08
        assert 0.70 <= params["subsample"] <= 1.00
        assert 0.55 <= params["colsample_bytree"] <= 1.00
        assert 0.0 <= params["reg_alpha"] <= 2.0
        assert 2.0 <= params["reg_lambda"] <= 20.0
        assert 0.0 <= params["gamma"] <= 1.5


def test_selection_is_lexicographic_and_requires_no_weighted_score() -> None:
    control = {"fold_1": 0.67, "fold_2": 0.68, "fold_3": 0.66}
    winner = select_best_trial(
        [
            _trial(1, 0.669, {"fold_1": 0.669, "fold_2": 0.681, "fold_3": 0.661}),
            _trial(0, 0.669, {"fold_1": 0.669, "fold_2": 0.679, "fold_3": 0.661}),
        ],
        control,
    )
    assert winner.number == 0
    assert winner.improvement_fold_count == 2
