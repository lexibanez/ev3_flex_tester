import sys
import uselect
import time
import json

# Import test modules
import AoA_cont
import aoa_short
import compute_distro
import compute_distro_short
import hover_aft_flex
import hover_aft_short
import hover_fore_flex
import hover_fore_short
import camera_flex
import camera_aft_flex
import camera_short
import camera_aft_short

# ---------------- Command handling ----------------
current_test = "aoa"  # Default test
cdist_mode = "continuity"  # "continuity" or "short" for Compute Distro
short_threshold = 1.5
test_should_switch = False
# Buffer for incomplete lines (readline() can block on partial data)
_command_buffer = b""
CALIBRATION_FILE = "resistance_calibration.json"
DEFAULT_CALIBRATION = {
    "r1": 100.0,
    "r2": 100.0,
    "demux_r": 100.0,
    "mux_r": 100.0,
    "supply_voltage": 3.3,
    "calibration_channel": 30,
    "calibration_test": "compute_distro",
}


def load_calibration():
    calibration = {}
    loaded = False
    for key in DEFAULT_CALIBRATION:
        calibration[key] = DEFAULT_CALIBRATION[key]
    try:
        with open(CALIBRATION_FILE, "r") as f:
            loaded = json.load(f)
        if isinstance(loaded, dict):
            for key in loaded:
                calibration[key] = loaded[key]
            loaded = True
        else:
            loaded = False
    except Exception:
        pass
    return calibration, loaded


def save_calibration(calibration):
    with open(CALIBRATION_FILE, "w") as f:
        json.dump(calibration, f)


current_calibration, current_calibration_loaded = load_calibration()


def measure_calibration_voltage():
    compute_distro.set_demux_channel(15)
    compute_distro.set_mux_channel(15)
    time.sleep_ms(5)
    raw_value = compute_distro.adc1.read_u16()
    voltage = (raw_value / 65535) * 3.3 * compute_distro.VDIV_SCALE
    return round(voltage, 6)

# Create poll object once for reuse
poll = uselect.poll()
poll.register(sys.stdin, uselect.POLLIN)

def apply_short_threshold():
    aoa_short.set_threshold(short_threshold)
    compute_distro_short.set_threshold(short_threshold)
    hover_aft_short.set_threshold(short_threshold)
    hover_fore_short.set_threshold(short_threshold)
    camera_short.set_threshold(short_threshold)
    camera_aft_short.set_threshold(short_threshold)


def check_for_command():
    """Check for incoming serial commands (non-blocking).
    Never use readline() - it blocks if only partial data has arrived,
    which freezes the Pico when switching tests rapidly.
    """
    global current_test, test_should_switch, cdist_mode, short_threshold, _command_buffer, current_calibration, current_calibration_loaded

    try:
        # Read only available bytes, one at a time, so we never block
        # Use stdin.read(1) which returns str in MicroPython; handle both str and bytes
        while poll.poll(0):
            ch = sys.stdin.read(1)
            if ch is None or len(ch) == 0:
                break
            # MicroPython stdin is text stream: read(1) returns str (e.g. "\n")
            if ch == "\n" or ch == "\r" or ch == b"\n" or ch == b"\r":
                if _command_buffer:
                    command = _command_buffer.decode("utf-8", "ignore").strip()
                    _command_buffer = b""
                    if command:
                        print("Received command:", command)
                        if command.startswith("test:"):
                            new_test = command.split(":")[1].strip()
                            if new_test in ["aoa", "aoa_short", "compute_distro", "hover_aft_flex", "hover_aft_short", "hover_fore_flex", "hover_fore_short", "camera_flex", "camera_aft_flex", "camera_short", "camera_aft_short"]:
                                if new_test != current_test:
                                    current_test = new_test
                                    test_should_switch = True
                                    print("Switching to test:", new_test)
                                    return True
                        elif command.startswith("mode:"):
                            new_mode = command.split(":")[1].strip()
                            if new_mode in ["continuity", "short"]:
                                cdist_mode = new_mode
                                print("Compute distro mode:", new_mode)
                                return False
                        elif command.startswith("short_threshold:"):
                            try:
                                short_threshold = float(command.split(":")[1].strip())
                                apply_short_threshold()
                                print("Short threshold:", short_threshold)
                            except Exception as e:
                                print("Short threshold error:", e)
                            return False
                        elif command == "get_calibration":
                            print(json.dumps({"calibration": current_calibration, "calibration_loaded": current_calibration_loaded}))
                            return False
                        elif command.startswith("set_calibration:"):
                            payload = command[len("set_calibration:"):].strip()
                            try:
                                loaded = json.loads(payload)
                                if isinstance(loaded, dict):
                                    for key in loaded:
                                        current_calibration[key] = loaded[key]
                                    save_calibration(current_calibration)
                                    current_calibration_loaded = True
                                    print(json.dumps({"calibration": current_calibration, "calibration_loaded": current_calibration_loaded, "calibration_saved": True}))
                            except Exception as e:
                                print("Calibration save error:", e)
                            return False
                        elif command == "measure_calibration":
                            try:
                                print(json.dumps({"calibration_measurement": {"channel": 30, "voltage": measure_calibration_voltage()}}))
                            except Exception as e:
                                print("Calibration measurement error:", e)
                            return False
            else:
                _command_buffer += ch.encode("utf-8") if isinstance(ch, str) else ch
                # Allow larger JSON payloads for multi-point calibration saves.
                if len(_command_buffer) > 4096:
                    _command_buffer = b""
    except Exception as e:
        print("Error reading command:", e)
        _command_buffer = b""

    return False

def should_exit_check():
    """Function to check if test should exit (used by test modules)"""
    global test_should_switch
    if check_for_command() or test_should_switch:
        test_should_switch = False
        return True
    return False

# ---------------- Main loop ----------------
def main():
    global current_test

    # Set exit checker functions for all test modules
    AoA_cont.set_exit_checker(should_exit_check)
    aoa_short.set_exit_checker(should_exit_check)
    compute_distro.set_exit_checker(should_exit_check)
    compute_distro_short.set_exit_checker(should_exit_check)
    hover_aft_flex.set_exit_checker(should_exit_check)
    hover_aft_short.set_exit_checker(should_exit_check)
    hover_fore_flex.set_exit_checker(should_exit_check)
    hover_fore_short.set_exit_checker(should_exit_check)
    camera_flex.set_exit_checker(should_exit_check)
    camera_aft_flex.set_exit_checker(should_exit_check)
    camera_short.set_exit_checker(should_exit_check)
    camera_aft_short.set_exit_checker(should_exit_check)
    apply_short_threshold()

    print("Pico Test Controller Started")
    print("Default test: AoA/Pitot Test")
    print("Waiting for commands...")
    print("Send commands: test:aoa, test:aoa_short, test:compute_distro, test:hover_aft_flex, test:hover_aft_short, test:hover_fore_flex, test:hover_fore_short, test:camera_flex, test:camera_aft_flex, test:camera_short, test:camera_aft_short")

    while True:
        # Run the selected test (will exit when command received)
        if current_test == "aoa":
            AoA_cont.run()
        elif current_test == "aoa_short":
            aoa_short.run()
        elif current_test == "compute_distro":
            if cdist_mode == "short":
                compute_distro_short.run()
            else:
                compute_distro.run()
        elif current_test == "hover_aft_flex":
            hover_aft_flex.run()
        elif current_test == "hover_aft_short":
            hover_aft_short.run()
        elif current_test == "hover_fore_flex":
            hover_fore_flex.run()
        elif current_test == "hover_fore_short":
            hover_fore_short.run()
        elif current_test == "camera_flex":
            camera_flex.run()
        elif current_test == "camera_aft_flex":
            camera_aft_flex.run()
        elif current_test == "camera_short":
            camera_short.run()
        elif current_test == "camera_aft_short":
            camera_aft_short.run()
        else:  # Default to AoA
            AoA_cont.run()

        # Small delay before checking commands again
        time.sleep_ms(50)

# Start main loop
if __name__ == "__main__":
    main()
