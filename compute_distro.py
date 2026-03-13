from machine import Pin, ADC  # type: ignore
import time
import json

# ---------------- GPIO setup ----------------
# Demux SEL pins: S3=pin0, S2=pin1, S1=pin2, S0=pin3
demux_s3 = Pin(1, Pin.OUT)  # S3
demux_s2 = Pin(0, Pin.OUT)  # S2
demux_s1 = Pin(2, Pin.OUT)  # S1
demux_s0 = Pin(3, Pin.OUT)  # S0

# Mux SEL pins: S3=pin8, S2=pin9, S1=pin10, S0=pin11
mux_s3 = Pin(9, Pin.OUT)   # S3
mux_s2 = Pin(8, Pin.OUT)   # S2
mux_s1 = Pin(10, Pin.OUT)  # S1
mux_s0 = Pin(11, Pin.OUT)  # S0

# ---------------- ADC setup ----------------
# ADC0 on RP2350 is typically GPIO26
adc0 = ADC(26)  # ADC0 channel
# ADC1 on RP2350 is typically GPIO27
adc1 = ADC(27)  # ADC1 channel

# ---------------- Channel selection functions ----------------
def set_demux_channel(channel):
    """Set demux to channel Y0-Y15
    S3=pin0, S2=pin1, S1=pin2, S0=pin3
    """
    # Set all pins in sequence to ensure proper switching
    demux_s3.value((channel >> 3) & 1)  # MSB
    demux_s2.value((channel >> 2) & 1)
    demux_s1.value((channel >> 1) & 1)
    demux_s0.value((channel >> 0) & 1)  # LSB
    time.sleep_us(10)  # Small delay to ensure pins are set

def set_mux_channel(channel):
    """Set mux to channel Y0-Y15
    S3=pin8, S2=pin9, S1=pin10, S0=pin11
    """
    # Set all pins in sequence to ensure proper switching
    mux_s3.value((channel >> 3) & 1)  # MSB
    mux_s2.value((channel >> 2) & 1)
    mux_s1.value((channel >> 1) & 1)
    mux_s0.value((channel >> 0) & 1)  # LSB
    time.sleep_us(10)  # Small delay to ensure pins are set

# ---------------- Main run generator ----------------
# Global flag for command checking (set by main.py)
should_exit = None

# Voltage divider R65=1k, R67=100k: ADC sees V*100/101; scale up for true MUX voltage
VDIV_SCALE = 101.0 / 100.0  # (R65 + R67) / R67

def set_exit_checker(checker_func):
    """Set the function to check if we should exit"""
    global should_exit
    should_exit = checker_func

def run():
    print("Compute Distro test started")
    # Define 30 channels: C1-C30
    # Pin mapping is REVERSED: Pin 1 → C30 (Y15, ADC1), Pin 30 → C1 (Y1, ADC0)
    # Signal names from P70/P71 connector (reversed order)
    signal_names = {
        1: "GND7",           # Pin 30 → C1 (Y1, ADC0)
        2: "COMP_D_GBE_P",   # Pin 29 → C2 (Y2, ADC0)
        3: "IMU_POCI_N",     # Pin 28 → C3 (Y3, ADC0)
        4: "COMP_D_GBE_N",   # Pin 27 → C4 (Y4, ADC0)
        5: "IMU_POCI_P",     # Pin 26 → C5 (Y5, ADC0)
        6: "COMP_C_GBE_P",   # Pin 25 → C6 (Y6, ADC0)
        7: "GND6",           # Pin 24 → C7 (Y7, ADC0)
        8: "COMP_C_GBE_N",   # Pin 23 → C8 (Y8, ADC0)
        9: "IMU_FSYNC_N",    # Pin 22 → C9 (Y9, ADC0)
        10: "COMP_B_GBE_P",  # Pin 21 → C10 (Y10, ADC0)
        11: "IMU_FSYNC_P",   # Pin 20 → C11 (Y11, ADC0)
        12: "COMP_B_GBE_N",  # Pin 19 → C12 (Y12, ADC0)
        13: "GND5",          # Pin 18 → C13 (Y13, ADC0)
        14: "COMP_A_GBE_P",  # Pin 17 → C14 (Y14, ADC0)
        15: "GND4",           # Pin 16 → C15 (Y15, ADC0)
        16: "COMP_A_GBE_N",  # Pin 15 → C16 (Y1, ADC1)
        17: "GND3",          # Pin 14 → C17 (Y2, ADC1)
        18: "VBUS4",         # Pin 13 → C18 (Y3, ADC1)
        19: "IMU_CS_P",      # Pin 12 → C19 (Y4, ADC1)
        20: "VBUS3",         # Pin 11 → C20 (Y5, ADC1)
        21: "IMU_CS_N",      # Pin 10 → C21 (Y6, ADC1)
        22: "VBUS2",         # Pin 9 → C22 (Y7, ADC1)
        23: "GND2",          # Pin 8 → C23 (Y8, ADC1)
        24: "VBUS1",         # Pin 7 → C24 (Y9, ADC1)
        25: "IMU_PICO_N",    # Pin 6 → C25 (Y10, ADC1)
        26: "IMU_5V",        # Pin 5 → C26 (Y11, ADC1)
        27: "IMU_PICO_P",    # Pin 4 → C27 (Y12, ADC1)
        28: "IMU_CLK_P",     # Pin 3 → C28 (Y13, ADC1)
        29: "GND1",          # Pin 2 → C29 (Y14, ADC1)
        30: "IMU_CLK_N"      # Pin 1 → C30 (Y15, ADC1)
    }

    # Define 30 channels: C1-C30
    # C1-C15: Y1-Y15 with ADC0
    # C16-C30: Y1-Y15 with ADC1
    test_channels = []
    for i in range(1, 31):  # C1 to C30
        test_channels.append({
            "channel": i,
            "signal": signal_names[i],
            "mux_channel": ((i - 1) % 15) + 1,  # Y1-Y15, repeating
            "adc": 0 if i <= 15 else 1  # ADC0 for C1-C15, ADC1 for C16-C30
        })
    print("Initialized {} channels".format(len(test_channels)))

    while True:
        # Check if we should exit (for test switching)
        if should_exit and should_exit():
            return

        results = []

        # Cycle through all 30 channels
        for ch_info in test_channels:
            # Check if we should exit between channels
            if should_exit and should_exit():
                return

            ch_num = ch_info["channel"]
            signal = ch_info["signal"]
            mux_ch = ch_info["mux_channel"]
            adc_num = ch_info["adc"]

            # Set both DEMUX and MUX to the same channel (Y1-Y15)
            set_demux_channel(mux_ch)
            set_mux_channel(mux_ch)

            # Allow settling time
            time.sleep_ms(2)

            # Read voltage from appropriate ADC
            if adc_num == 0:
                raw_value = adc0.read_u16()
            else:
                raw_value = adc1.read_u16()

            voltage = (raw_value / 65535) * 3.3 * VDIV_SCALE

            # Determine status (threshold: 1.5V for continuity test - same as other tests)
            status = "PASS" if voltage >= 1.5 else "FAIL"

            results.append({
                "channel": ch_num,
                "signal": signal,
                "voltage": round(voltage, 3),
                "status": status
            })

        # Send JSON data for GUI (standardized format)
        # Format: {"test_name": "Test Name", "channels": [{"channel": N, "signal": "SignalName", "voltage": V, "status": "PASS/FAIL"}]}
        json_output = json.dumps({
            "test_name": "Compute Distro Flex Continuity Test",
            "channels": results
        })
        print(json_output)
        # Note: sys.stdout.flush() not available in MicroPython - print() flushes automatically

        # Delay between full cycles (same as other tests)
        time.sleep_ms(10)

# Only run if executed directly (not when imported)
if __name__ == "__main__":
    run()
