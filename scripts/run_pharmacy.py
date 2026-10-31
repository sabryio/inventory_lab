"""Quick single-replication run of the baseline pharmacy experiment."""

from inventory_lab.application.factory import SimulationFactory
from inventory_lab.infrastructure.presets import pharmacy_experiment

spec = pharmacy_experiment(replications=1, horizon_days=365)
factory = SimulationFactory(spec)

print(f"Experiment : {spec.name}")
print(f"Horizon    : {spec.horizon_days}d  |  Shelf life: {spec.shelf_life_days:.0f}d")
print()
print(f"{'Candidate':<25}  {'Fill':>6}  {'Waste':>5}  {'Cost':>9}  {'Orders':>6}")
print("-" * 60)

for c in spec.candidates:
    r = factory.create_engine(c, seed=42, replication=0).run()
    k = r.kpis
    print(
        f"{c.name:<25}  {k.fill_rate:>6.1%}  {k.units_wasted:>5d}  {k.total_cost:>9.0f}  {k.orders_placed:>6d}"
    )
