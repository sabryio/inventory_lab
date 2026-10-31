"""Pharmacy stress experiment — single replication. All values in EGP."""

from inventory_lab.application.factory import SimulationFactory
from inventory_lab.infrastructure.presets import pharmacy_stress_experiment

spec = pharmacy_stress_experiment(replications=1, horizon_days=365)
factory = SimulationFactory(spec)

print(f"Experiment : {spec.name}")
print(f"Horizon    : {spec.horizon_days}d  |  Shelf life: {spec.shelf_life_days:.0f}d")
print(f"Unit cost  : EGP {spec.lanes[0].unit_cost:,.0f}")
print()
print(
    f"{'Candidate':<25}  {'Fill':>6}  {'Waste':>5}  {'Cost (EGP)':>12}  {'Orders':>6}"
)
print("-" * 65)

for c in spec.candidates:
    r = factory.create_engine(c, seed=42, replication=0).run()
    k = r.kpis
    print(
        f"{c.name:<25}  {k.fill_rate:>6.1%}  {k.units_wasted:>5d}"
        f"  {k.total_cost:>12,.0f}  {k.orders_placed:>6d}"
    )
