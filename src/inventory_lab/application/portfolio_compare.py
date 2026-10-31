"""Use case: compare consolidated vs. independent ordering for a SKU portfolio."""

from __future__ import annotations

from statistics import mean, stdev
from math import sqrt

from inventory_lab.application.portfolio_specs import PortfolioSpec
from inventory_lab.domain.base import ValueObject
from inventory_lab.simulation.portfolio_engine import PortfolioEngine, PortfolioRunResult
from inventory_lab.simulation.result import SimulationResult


class SkuSummary(ValueObject):
    """Aggregated KPIs for a single SKU across all replications."""

    sku_id: str
    mean_total_cost: float
    mean_fill_rate: float
    mean_ready_rate: float
    mean_avg_on_hand: float
    mean_orders_placed: float
    mean_units_wasted: float
    meets_service_target: bool


class PortfolioComparisonResult(ValueObject):
    """Outcome of a consolidated vs. independent ordering comparison."""

    experiment: str
    replications: int
    horizon_days: int
    n_skus: int
    target_service_level: float

    # Per-SKU summaries (independent ordering baseline)
    sku_summaries: tuple[SkuSummary, ...]

    # Consolidated totals
    total_cost_independent: float
    total_cost_consolidated: float
    fixed_cost_saved: float
    savings_pct: float

    # Portfolio-level service
    portfolio_fill_rate: float      # average across all SKUs
    all_skus_meet_target: bool


def _summarise_results(
    runs: list[SimulationResult],
) -> tuple[float, float, float, float, float, float]:
    """Return (mean_cost, mean_fill, mean_ready, mean_oh, mean_orders, mean_wasted)."""
    costs   = [r.kpis.total_cost      for r in runs]
    fills   = [r.kpis.fill_rate       for r in runs]
    readys  = [r.kpis.ready_rate      for r in runs]
    ohs     = [r.kpis.avg_on_hand     for r in runs]
    orders  = [r.kpis.orders_placed   for r in runs]
    wasted  = [r.kpis.units_wasted    for r in runs]
    return (
        mean(costs), mean(fills), mean(readys),
        mean(ohs), mean(orders), mean(wasted),
    )


class ComparePortfolioStrategies:
    """Single responsibility: run the same portfolio twice and measure the saving.

    Runs with `consolidation_enabled=True` and `consolidation_enabled=False`, using
    the same seeds for common random numbers.
    """

    def execute(self, spec: PortfolioSpec) -> PortfolioComparisonResult:
        # ------------------------------------------------------------------
        # 1. Run both strategies across all replications
        # ------------------------------------------------------------------
        cons_runs:  list[PortfolioRunResult] = []
        indep_runs: list[PortfolioRunResult] = []

        cons_spec  = spec
        indep_spec = spec.model_copy(update={"consolidation_enabled": False})

        for r in range(spec.replications):
            cons_runs.append(
                PortfolioEngine(cons_spec,  seed=spec.seed + r, replication=r).run()
            )
            indep_runs.append(
                PortfolioEngine(indep_spec, seed=spec.seed + r, replication=r).run()
            )

        # ------------------------------------------------------------------
        # 2. Aggregate per-SKU metrics (from independent runs as baseline)
        # ------------------------------------------------------------------
        sku_ids = [sku.sku_id for sku in spec.skus]
        sku_summaries: list[SkuSummary] = []

        for sku_id in sku_ids:
            runs = [rep.sku_results[sku_id] for rep in indep_runs]
            mc, mf, mr, moh, mo, mw = _summarise_results(runs)
            sku_summaries.append(
                SkuSummary(
                    sku_id=sku_id,
                    mean_total_cost=mc,
                    mean_fill_rate=mf,
                    mean_ready_rate=mr,
                    mean_avg_on_hand=moh,
                    mean_orders_placed=mo,
                    mean_units_wasted=mw,
                    meets_service_target=mf >= spec.target_service_level,
                )
            )

        # ------------------------------------------------------------------
        # 3. Compute total costs and consolidation saving
        # ------------------------------------------------------------------
        def _total_sku_cost(run: PortfolioRunResult) -> float:
            return sum(r.kpis.total_cost for r in run.sku_results.values())

        indep_total_per_rep = [_total_sku_cost(r) for r in indep_runs]
        cons_total_per_rep  = [
            _total_sku_cost(r) - r.total_fixed_cost_saved
            for r in cons_runs
        ]
        saved_per_rep = [r.total_fixed_cost_saved for r in cons_runs]

        mean_indep = mean(indep_total_per_rep)
        mean_cons  = mean(cons_total_per_rep)
        mean_saved = mean(saved_per_rep)
        savings_pct = (mean_saved / mean_indep * 100) if mean_indep > 0 else 0.0

        # ------------------------------------------------------------------
        # 4. Portfolio-level service
        # ------------------------------------------------------------------
        portfolio_fill = mean(s.mean_fill_rate for s in sku_summaries)
        all_meet = all(s.meets_service_target for s in sku_summaries)

        return PortfolioComparisonResult(
            experiment=spec.name,
            replications=spec.replications,
            horizon_days=spec.horizon_days,
            n_skus=len(spec.skus),
            target_service_level=spec.target_service_level,
            sku_summaries=tuple(sku_summaries),
            total_cost_independent=mean_indep,
            total_cost_consolidated=mean_cons,
            fixed_cost_saved=mean_saved,
            savings_pct=savings_pct,
            portfolio_fill_rate=portfolio_fill,
            all_skus_meet_target=all_meet,
        )
