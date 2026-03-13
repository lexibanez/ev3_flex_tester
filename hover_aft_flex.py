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
adc0 = ADC(26)  # ADC0
adc1 = ADC(27)  # ADC1

# ---------------- Channel selection ----------------
def net_to_y(net):
    """Convert net 1-30 to Y1-Y15 (same code used twice: 1-15 ADC0, 16-30 ADC1)."""
    return ((net - 1) % 15) + 1

def set_demux_channel(channel):
    """Set demux to channel Y0-Y15."""
    demux_s3.value((channel >> 3) & 1)
    demux_s2.value((channel >> 2) & 1)
    demux_s1.value((channel >> 1) & 1)
    demux_s0.value((channel >> 0) & 1)
    time.sleep_us(10)

def set_mux_channel(channel):
    """Set mux to channel Y0-Y15."""
    mux_s3.value((channel >> 3) & 1)
    mux_s2.value((channel >> 2) & 1)
    mux_s1.value((channel >> 1) & 1)
    mux_s0.value((channel >> 0) & 1)
    time.sleep_us(10)

# ---------------- Main run generator ----------------
should_exit = None

def set_exit_checker(checker_func):
    global should_exit
    should_exit = checker_func

# ADC selection: True = use MUX net (1-15 → ADC0, 16-30 → ADC1). False = use DEMUX net.
# If continuity fails when wires are connected, try the other option to match your hardware.
ADC_BY_MUX = True

# Voltage divider R65=1k, R67=100k: ADC sees V*100/101; scale up for true MUX voltage
VDIV_SCALE = 101.0 / 100.0  # (R65 + R67) / R67

# Pin matching: (demux_net, mux_net, signal_name)
# MUX 4 shared by GND1_HOVAFT (DEMUX 24) and GND2_HOVAFT (DEMUX 25)
HOVER_AFT_CHANNELS = [
    (21, 23, "T1_IN_P"),      # MUX swapped with T1_OUT_N
    (22, 1, "28V_SERVO"),
    (23, 21, "T1_IN_N"),
    (24, 4, "GND1_HOVAFT"),
    (25, 4, "GND2_HOVAFT"),
    (26, 2, "RS485_P"),
    (27, 22, "T1_OUT_P"),
    (28, 3, "RS485_N"),
    (29, 24, "T1_OUT_N"),     # MUX swapped with T1_IN_P
    (30, 26, "CHASSIS"),
]

def run():
    print("Hover Aft Flex test started")
    test_channels = []
    for i, (d_net, m_net, signal) in enumerate(HOVER_AFT_CHANNELS, start=1):
        test_channels.append({
            "channel": i,
            "signal": signal,
            "demux_net": d_net,
            "mux_net": m_net,
            "demux_y": net_to_y(d_net),
            "mux_y": net_to_y(m_net),
            "adc": 0 if (1 <= (m_net if ADC_BY_MUX else d_net) <= 15) else 1,
        })
    print("Initialized %d channels" % len(test_channels))

    while True:
        if should_exit and should_exit():
            return

        results = []
        for ch_info in test_channels:
            if should_exit and should_exit():
                return

            ch_num = ch_info["channel"]
            signal = ch_info["signal"]
            set_demux_channel(ch_info["demux_y"])
            set_mux_channel(ch_info["mux_y"])
            time.sleep_ms(5)  # Settling so voltage reaches ADC when wire is connected

            if ch_info["adc"] == 0:
                raw_value = adc0.read_u16()
            else:
                raw_value = adc1.read_u16()
            voltage = (raw_value / 65535) * 3.3 * VDIV_SCALE
            status = "PASS" if voltage >= 0.25 else "FAIL"
            results.append({
                "channel": ch_num,
                "signal": signal,
                "voltage": round(voltage, 3),
                "status": status
            })

        json_output = json.dumps({
            "test_name": "Hover Aft Flex Test",
            "channels": results
        })
        print(json_output)
        time.sleep_ms(10)

if __name__ == "__main__":
    run()
