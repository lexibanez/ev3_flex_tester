# Camera Aft Flex (P52B): same tester DEMUX/MUX as Fore; PA block uses PF nets, SA block uses SF nets
from machine import Pin, ADC  # type: ignore
import time
import json

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

VDIV_SCALE = 101.0 / 100.0

# P52B (Aft) channels in tester DEMUX order, matching Camera Flex numbering style.
# PA block uses the same tester nets as Fore PF; SA block uses the same tester nets as Fore SF.
CAMERA_AFT_CHANNELS = [
    (1, 1, "GND"),
    (2, 1, "GND"),
    (3, 1, "GND"),
    (4, 15, "GMSL2_SA_N"),
    (15, 22, "BLOWER_SA_A"), #
    (6, 13, "GMSL2_SA_P"),
    (13, 24, "BLOWER_SA_B"), #
    (8, 1, "GND"),
    (11, 26, "BLOWER_SA_C"), #
    (10, 19, "V_CAM_SA"),
    (9, 25, "BLOWER_PA_C"), #
    (12, 1, "GND"),
    (7, 23, "BLOWER_PA_B"), #
    (14, 5, "GMSL2_PA_N"),
    (5, 21, "BLOWER_PA_A"), #
    (16, 3, "GMSL2_PA_P"),
    (17, 1, "GND"),
    (18, 1, "GND"),
    (19, 1, "GND"),
    (20, 9, "V_CAM_PA"),
]

def run():
    print("Camera Aft Flex test started")
    test_channels = []
    for i, (d_net, m_net, signal) in enumerate(CAMERA_AFT_CHANNELS, start=1):
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

        print(json.dumps({
            "test_name": "Camera Aft Flex Test",
            "channels": results
        }))
        time.sleep_ms(10)

if __name__ == "__main__":
    run()
