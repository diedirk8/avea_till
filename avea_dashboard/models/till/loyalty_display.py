"""Customer-facing loyalty point display helpers (not calculation)."""


def format_loyalty_points_display(points):
    """Format loyalty points for display without changing stored values."""
    try:
        value = float(points)
    except (TypeError, ValueError):
        return "0"
    if not value:
        return "0"
    rounded = round(value, 2)
    if rounded == int(rounded):
        return str(int(rounded))
    return f"{rounded:.2f}"
