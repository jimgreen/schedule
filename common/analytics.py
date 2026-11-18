"""Energy accounting from dispatch values; supports historical plan versions."""


def energy_summary(dispatch, interval_minutes):
    dt = interval_minutes / 60
    summary = dict.fromkeys(('demand_kwh', 'diesel_kwh', 'renewable_kwh', 'curtailed_kwh',
                             'import_kwh', 'export_kwh', 'charge_kwh', 'discharge_kwh',
                             'flexible_kwh', 'lost_load_kwh'), 0.0)
    for row in dispatch:
        values = {
            'demand': row.get('demand_kw', 0),
            'diesel': sum(g['power_kw'] for g in row.get('generators', {}).values()),
            'renewable': sum(row.get('renewables', {}).values()),
            'curtailed': row.get('renewable_curtailment_kw', 0),
            'import': row.get('grid_import_kw', 0), 'export': row.get('grid_export_kw', 0),
            'charge': sum(b['charge_kw'] for b in row.get('batteries', {}).values()),
            'discharge': sum(b['discharge_kw'] for b in row.get('batteries', {}).values()),
            'flexible': row.get('flexible_load_kw', 0), 'lost_load': row.get('lost_load_kw', 0),
        }
        for key, power in values.items():
            summary[key + '_kwh'] += power * dt
    return {key: round(val, 4) for key, val in summary.items()}
