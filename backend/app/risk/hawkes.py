"""Self-exciting (Hawkes) forecast of serious complaints, exponential kernel.

Intensity:  lambda(t) = mu + alpha * beta * sum_{t_i < t} exp(-beta (t - t_i))
  mu    background rate of serious complaints (per day)
  alpha branching ratio (expected follow-up serious complaints triggered by one), 0 <= alpha < 1
  beta  decay rate (1/days); ln(2)/beta is the half-life of the excitation

Fitting: maximum likelihood (L-BFGS-B, multiple starts) with bounds
beta in [1/365, 1/7] per day and alpha <= 0.9, using the standard O(n) recursion.
Safeguards (no fabricated precision):
  * fewer than MIN_EVENTS serious events, a failed/unstable fit, or alpha at its bound ->
    POOLED fallback: alpha and beta from a pooled fit over all institutions and an
    institution background rate shrunk towards the pooled rate (Gamma prior worth 2 years);
  * zero events -> BASELINE: pooled background rate only, LOW confidence.
Forecast for the next H days (default 182.5):
  P(at least one serious complaint) = 1 - exp(-[mu*H + alpha * sum_i (e^{-beta(T-t_i)} - e^{-beta(T+H-t_i)})])
which is exact under the model given the history. A range comes from sampling the
background rate from its Gamma posterior (fixed RNG seed => reproducible).
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np

MIN_EVENTS = 8
BETA_BOUNDS = (1 / 365.0, 1 / 7.0)
ALPHA_MAX = 0.9
PRIOR_DAYS = 730.0


def log_likelihood(times: np.ndarray, T: float, mu: float, alpha: float, beta: float) -> float:
    if mu <= 0 or alpha < 0 or beta <= 0:
        return -1e18
    ll = 0.0
    A = 0.0
    prev = None
    for t in times:
        if prev is not None:
            A = math.exp(-beta * (t - prev)) * (1.0 + A)
        lam = mu + alpha * beta * A
        ll += math.log(max(lam, 1e-300))
        prev = t
    comp = mu * T + alpha * float(np.sum(1.0 - np.exp(-beta * (T - times))))
    return ll - comp


def _unpack(x: np.ndarray) -> tuple[float, float, float]:
    mu = math.exp(x[0])
    alpha = ALPHA_MAX / (1.0 + math.exp(-x[1]))
    beta = math.exp(x[2])
    return mu, alpha, beta


def fit(times: list[float], T: float, fixed: tuple[float, float] | None = None) -> dict[str, Any]:
    """MLE fit. If `fixed=(alpha, beta)` only mu is estimated (closed-form-ish 1-D search)."""
    from scipy.optimize import minimize, minimize_scalar

    ts = np.array(sorted(times), dtype=float)
    n = len(ts)
    if fixed is not None:
        alpha, beta = fixed

        def nll_mu(lm: float) -> float:
            return -log_likelihood(ts, T, math.exp(lm), alpha, beta)

        r = minimize_scalar(nll_mu, bounds=(math.log(1e-7), math.log(5.0)), method="bounded")
        mu = math.exp(r.x)
        return {"mu": mu, "alpha": alpha, "beta": beta, "loglik": -r.fun, "converged": bool(r.success)}
    best = None
    lb, ub = math.log(BETA_BOUNDS[0]), math.log(BETA_BOUNDS[1])
    base_mu = max(n, 1) / T
    for a0, b0 in ((0.2, 1 / 60.0), (0.5, 1 / 30.0), (0.05, 1 / 180.0)):
        x0 = np.array([math.log(base_mu * (1 - a0)), math.log(a0 / (ALPHA_MAX - a0)), math.log(b0)])

        def nll(x: np.ndarray) -> float:
            mu, alpha, beta = _unpack(x)
            return -log_likelihood(ts, T, mu, alpha, beta)

        r = minimize(nll, x0, method="L-BFGS-B",
                     bounds=[(math.log(1e-7), math.log(5.0)), (-12.0, 12.0), (lb, ub)])
        if best is None or r.fun < best.fun:
            best = r
    assert best is not None
    mu, alpha, beta = _unpack(best.x)
    return {"mu": mu, "alpha": alpha, "beta": beta, "loglik": -best.fun, "converged": bool(best.success)}


def fit_pooled(series: list[list[float]], T: float) -> dict[str, Any]:
    """Shared (alpha, beta) across institutions; mu_i profiled as n_i (1 - alpha) / T."""
    from scipy.optimize import minimize

    arrays = [np.array(sorted(s), dtype=float) for s in series if len(s) > 0]
    if not arrays:
        return {"alpha": 0.0, "beta": 1 / 60.0, "mu_mean": 0.0, "converged": False}

    def nll(x: np.ndarray) -> float:
        alpha = ALPHA_MAX / (1.0 + math.exp(-x[0]))
        beta = math.exp(x[1])
        total = 0.0
        for ts in arrays:
            mu = max(len(ts) * (1 - alpha) / T, 1e-7)
            total += log_likelihood(ts, T, mu, alpha, beta)
        return -total

    best = None
    for a0, b0 in ((0.2, 1 / 60.0), (0.4, 1 / 30.0)):
        x0 = np.array([math.log(a0 / (ALPHA_MAX - a0)), math.log(b0)])
        r = minimize(nll, x0, method="L-BFGS-B",
                     bounds=[(-12.0, 12.0), (math.log(BETA_BOUNDS[0]), math.log(BETA_BOUNDS[1]))])
        if best is None or r.fun < best.fun:
            best = r
    assert best is not None
    alpha = ALPHA_MAX / (1.0 + math.exp(-best.x[0]))
    beta = math.exp(best.x[1])
    counts = [len(s) for s in series]
    mu_mean = (sum(counts) / max(1, len(series))) * (1 - alpha) / T
    return {"alpha": alpha, "beta": beta, "mu_mean": mu_mean, "converged": bool(best.success)}


def intensity(times: list[float], t: float, mu: float, alpha: float, beta: float) -> float:
    past = np.array([s for s in times if s < t], dtype=float)
    return mu + alpha * beta * float(np.sum(np.exp(-beta * (t - past)))) if past.size else mu


def prob_at_least_one(times: list[float], T: float, H: float, mu: float, alpha: float, beta: float) -> float:
    ts = np.array(times, dtype=float)
    excite = alpha * float(np.sum(np.exp(-beta * (T - ts)) - np.exp(-beta * (T + H - ts)))) if ts.size else 0.0
    return 1.0 - math.exp(-(mu * H + excite))


def forecast(times: list[float], T: float, pooled: dict[str, Any], horizon: float = 182.5,
             seed: int = 26264) -> dict[str, Any]:
    """Fit (or fall back) and forecast the next `horizon` days for one institution."""
    n = len(times)
    notes: list[str] = []
    status = "FITTED"
    params: dict[str, Any] | None = None
    if n >= MIN_EVENTS:
        try:
            params = fit(times, T)
            if not params["converged"] or params["alpha"] >= ALPHA_MAX - 0.01 or not math.isfinite(params["loglik"]):
                notes.append("Institution-level fit was unstable; using pooled parameters.")
                params = None
        except Exception:  # pragma: no cover - numerical safety net
            notes.append("Institution-level fit failed; using pooled parameters.")
            params = None
    else:
        notes.append(f"Only {n} serious complaint(s) on record (< {MIN_EVENTS}); a reliable institution-level fit "
                     "is not supported.")
    if params is None:
        alpha, beta = float(pooled["alpha"]), float(pooled["beta"])
        m0 = float(pooled["mu_mean"])
        mu = ((1 - alpha) * n + m0 * PRIOR_DAYS) / (T + PRIOR_DAYS)
        params = {"mu": mu, "alpha": alpha, "beta": beta, "loglik": None, "converged": True}
        status = "BASELINE_NO_EVENTS" if n == 0 else "POOLED_FALLBACK"
    mu, alpha, beta = params["mu"], params["alpha"], params["beta"]
    p = prob_at_least_one(times, T, horizon, mu, alpha, beta)
    # Uncertainty: background rate from its Gamma posterior (shape ~ background events + 0.5).
    rng = np.random.default_rng(seed + n)
    n_bg = max(mu * T, 0.0)
    shape = n_bg + 0.5
    samples = rng.gamma(shape, mu / shape if shape > 0 else 1e-6, size=300)
    ps = [prob_at_least_one(times, T, horizon, float(m), alpha, beta) for m in samples]
    lo, hi = float(np.percentile(ps, 10)), float(np.percentile(ps, 90))
    lam_now = intensity(times, T, mu, alpha, beta)
    lam_prev = intensity(times, T - horizon, mu, alpha, beta)
    ratio = lam_now / lam_prev if lam_prev > 0 else 1.0
    trend = "RISING" if ratio >= 1.25 else "FALLING" if ratio <= 0.8 else "STABLE"
    last6 = sum(1 for t in times if T - horizon <= t <= T)
    prev6 = sum(1 for t in times if T - 2 * horizon <= t < T - horizon)
    expected = mu * horizon / (1 - alpha) + alpha / (1 - alpha) * float(
        np.sum(np.exp(-beta * (T - np.array(times))) - np.exp(-beta * (T + horizon - np.array(times))))) if times else mu * horizon / (1 - alpha)
    confidence = "HIGH" if status == "FITTED" and n >= 20 else "MEDIUM" if status == "FITTED" else "LOW"
    return {
        "status": status, "n_events": n, "horizon_days": horizon,
        "probability": round(p, 3), "interval_80": [round(lo, 3), round(hi, 3)],
        "expected_events": round(expected, 2),
        "params": {"mu_per_year": round(mu * 365, 3), "alpha": round(alpha, 3), "beta_per_day": round(beta, 4),
                   "excitation_half_life_days": round(math.log(2) / beta, 1)},
        "intensity_now_per_year": round(lam_now * 365, 3), "intensity_6m_ago_per_year": round(lam_prev * 365, 3),
        "trend": trend, "trend_ratio": round(ratio, 2), "events_last_6m": last6, "events_prev_6m": prev6,
        "confidence": confidence, "notes": notes,
    }
