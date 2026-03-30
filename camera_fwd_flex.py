from machine import Pin, ADC  # type: ignore
import time
import json

# ---------------- GPIO setup ----------------
demux_s3 = Pin(1, Pin.OUT)
demux_s2 = Pin(0, Pin.OUT)
demux_s1 = Pin(2, Pin.OUT)
demux_s0 = Pin(3, Pin.OUT)

mux_s3 = Pin(9, Pin.OUT)
mux_s2 = Pin(8, Pin.OUT)
mux_s1 = Pin(10, Pin.OUT)
mux_s0 = Pin(11, Pin.OUT)

adc0 = ADC(26)
adc1 = ADC(27)

def net_to_y(net):
    return ((net - 1) % 15) + 1

def set_demux_channel(channel):
    demux_s3.value((channel >> 3) & 1)
    demux_s2.value((channel >> 2) & 1)
    demux_s1.value((channel >> 1) & 1)
    demux_s0.value((channel >> 0) & 1)
    time.sleep_us(10)

def set_mux_channel(channel):
    mux_s3.value((channel >> 3) & 1)
    mux_s2.value((channel >> 2) & 1)
    mux_s1.value((channel >> 1) & 1)
    mux_s0.value((channel >> 0) & 1)
    time.sleep_us(10)

should_exit = None

def set_exit_checker(checker_func):
    global should_exit
    should_exit = checker_func

# Voltage divider R65=1k, R67=100k: ADC sees V*100/101; scale up for true MUX voltage
VDIV_SCALE = 101.0 / 100.0  # (R65 + R67) / R67

# Pin matching: (demux_net, mux_net, signal_name)
# Blower pins: MUX 21-26 per assignment (BLOWER_SF_A=21, BLOWER_PF_A=22, etc.)
CAMERA_FLEX_CHANNELS = [
    (1, 1, "GND8"), #
    (2, 4, "GND4"), 
    (3, 4, "GND7"), 
    (4, 5, "GMSL2_PF_N"),
    (5, 22, "BLOWER_PF_A"),  
    (6, 3, "GMSL2_PF_P"),
    (7, 24, "BLOWER_PF_B"),  
    (8, 1, "GND3"), #
    (9, 26, "BLOWER_PF_C"),  
    (10, 9, "V_CAM_PF"),
    (11, 25, "BLOWER_SF_C"),   
    (12, 1, "GND2"), #
    (13, 23, "BLOWER_SF_B"), 
    (14, 15, "GMSL2_SF_N"),
    (15, 21, "BLOWER_SF_A"),
    (16, 13, "GMSL2_SF_P"),
    (17, 4, "GND6"),
    (18, 4, "GND1"),
    (19, 1, "GND5"), #
    (20, 19, "V_CAM_SF"),
]

def run():
    print("Camera Flex test started")
    test_channels = []
    for i, (d_net, m_net, signal) in enumerate(CAMERA_FLEX_CHANNELS, start=1):
        test_channels.append({
            "channel": i,
            "signal": signal,
            "demux_net": d_net,
            "demux_y": net_to_y(d_net),
            "mux_net": m_net,
            "mux_y": net_to_y(m_net),
            "adc": 0 if 1 <= m_net <= 15 else 1,
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
            time.sleep_ms(2)

            if ch_info["adc"] == 0:
                raw_value = adc0.read_u16()
            else:
                raw_value = adc1.read_u16()
            voltage = (raw_value / 65535) * 3.3 * VDIV_SCALE
            status = "PASS" if voltage >= 1.5 else "FAIL"
            results.append({
                "channel": ch_num,
                "signal": signal,
                "voltage": round(voltage, 3),
                "status": status
            })

        json_output = json.dumps({
            "test_name": "Camera Flex Test",
            "channels": results
        })
        print(json_output)
        time.sleep_ms(10)

if __name__ == "__main__":
    run()
