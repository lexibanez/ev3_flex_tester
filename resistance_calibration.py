import json
import os


DEFAULT_CALIBRATION = {
    "r1": 100.0,
    "r2": 100.0,
    "demux_r": 100.0,
    "mux_r": 100.0,
    "supply_voltage": 3.3,
    "calibration_channel": 30,
    "calibration_test": "compute_distro",
    "calibration_note": "Calibrated from Compute Distro C30 (Y15, ADC1).",
}

DEFAULT_CALIBRATION_POINTS = [1.0, 10.0, 100.0, 1000.0]


def calibration_file_path(base_dir):
    return os.path.join(base_dir, "resistance_calibration.json")


def load_calibration(base_dir):
    calibration = dict(DEFAULT_CALIBRATION)
    path = calibration_file_path(base_dir)
    try:
        with open(path, "r", encoding="utf-8") as f:
            loaded = json.load(f)
        if isinstance(loaded, dict):
            calibration.update(loaded)
    except FileNotFoundError:
        pass
    except Exception as exc:
        print("Could not load calibration file:", exc)
    return calibration


def save_calibration(base_dir, calibration):
    path = calibration_file_path(base_dir)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(calibration, f, indent=2)


def base_resistance_from_voltage(voltage, calibration):
    if voltage is None:
        return None

    try:
        voltage = float(voltage)
    except (TypeError, ValueError):
        return None

    if voltage <= 0:
        return None

    supply_voltage = float(calibration.get("supply_voltage", 3.3))
    r2 = float(calibration.get("r2", 100.0))
    offset = float(calibration.get("demux_r", 100.0)) + float(calibration.get("mux_r", 100.0)) + float(calibration.get("r1", 100.0))
    return (supply_voltage * r2 / voltage) - offset


def _interpolate_points(x_value, points):
    if not points:
        return x_value

    points = sorted(points, key=lambda item: float(item["raw_resistance"]))
    x_value = float(x_value)

    if x_value <= float(points[0]["raw_resistance"]):
        return float(points[0]["known_resistance_ohms"])
    if x_value >= float(points[-1]["raw_resistance"]):
        return float(points[-1]["known_resistance_ohms"])

    for idx in range(len(points) - 1):
        left = points[idx]
        right = points[idx + 1]
        x0 = float(left["raw_resistance"])
        x1 = float(right["raw_resistance"])
        if x0 <= x_value <= x1:
            if abs(x1 - x0) < 1e-12:
                return float(left["known_resistance_ohms"])
            ratio = (x_value - x0) / (x1 - x0)
            y0 = float(left["known_resistance_ohms"])
            y1 = float(right["known_resistance_ohms"])
            return y0 + (y1 - y0) * ratio

    return x_value


def resistance_from_voltage(voltage, calibration):
    base_resistance = base_resistance_from_voltage(voltage, calibration)
    if base_resistance is None:
        return None

    points = calibration.get("calibration_points", [])
    if isinstance(points, list) and len(points) >= 2:
        try:
            return _interpolate_points(base_resistance, points)
        except Exception:
            return base_resistance
    return base_resistance


def solve_calibration_from_points(voltage_a, resistance_a, voltage_b, resistance_b, calibration=None):
    calibration = dict(DEFAULT_CALIBRATION if calibration is None else calibration)

    voltage_a = float(voltage_a)
    voltage_b = float(voltage_b)
    resistance_a = float(resistance_a)
    resistance_b = float(resistance_b)

    if voltage_a <= 0 or voltage_b <= 0:
        raise ValueError("Captured voltages must be above 0 V.")
    if abs(voltage_a - voltage_b) < 1e-9:
        raise ValueError("Captured voltages are identical. Use two different resistor values.")

    inv_a = 1.0 / voltage_a
    inv_b = 1.0 / voltage_b
    if abs(inv_a - inv_b) < 1e-12:
        raise ValueError("Calibration points are too close together.")

    k = (resistance_a - resistance_b) / (inv_a - inv_b)
    offset = (k / voltage_a) - resistance_a
    supply_voltage = float(calibration.get("supply_voltage", 3.3))
    demux_r = float(calibration.get("demux_r", 100.0))
    mux_r = float(calibration.get("mux_r", 100.0))
    r2 = k / supply_voltage
    r1 = offset - demux_r - mux_r

    if r2 <= 0:
        raise ValueError("Solved R2 is not positive. Check the captured readings.")

    calibration["r1"] = round(r1, 6)
    calibration["r2"] = round(r2, 6)
    calibration["last_calibration"] = {
        "point_a": {"resistance_ohms": resistance_a, "voltage": round(voltage_a, 6)},
        "point_b": {"resistance_ohms": resistance_b, "voltage": round(voltage_b, 6)},
    }
    return calibration


def solve_calibration_from_four_points(captured_points, calibration=None):
    calibration = dict(DEFAULT_CALIBRATION if calibration is None else calibration)
    if not isinstance(captured_points, list) or len(captured_points) < 4:
        raise ValueError("Four calibration points are required.")

    sorted_points = sorted(
        [{"resistance_ohms": float(p["resistance_ohms"]), "voltage": float(p["voltage"])} for p in captured_points],
        key=lambda item: item["resistance_ohms"],
    )

    endpoint_low = sorted_points[0]
    endpoint_high = sorted_points[-1]
    calibration = solve_calibration_from_points(
        endpoint_low["voltage"],
        endpoint_low["resistance_ohms"],
        endpoint_high["voltage"],
        endpoint_high["resistance_ohms"],
        calibration,
    )

    solved_points = []
    for point in sorted_points:
        raw_resistance = base_resistance_from_voltage(point["voltage"], calibration)
        if raw_resistance is None:
            raise ValueError("Could not solve raw resistance for one of the calibration points.")
        solved_points.append({
            "known_resistance_ohms": round(point["resistance_ohms"], 6),
            "voltage": round(point["voltage"], 6),
            "raw_resistance": round(raw_resistance, 6),
        })

    calibration["calibration_points"] = solved_points
    calibration["last_calibration"] = {
        "points": solved_points,
        "method": "four_point_piecewise",
    }
    return calibration
