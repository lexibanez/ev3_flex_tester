# Compute Distro short test: hold one DEMUX high, scan MUX; high on wrong MUX = short
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

def set_demux(ch):
    demux_s3.value((ch >> 3) & 1)
    demux_s2.value((ch >> 2) & 1)
    demux_s1.value((ch >> 1) & 1)
    demux_s0.value((ch >> 0) & 1)
    time.sleep_us(10)

def set_mux(ch):
    mux_s3.value((ch >> 3) & 1)
    mux_s2.value((ch >> 2) & 1)
    mux_s1.value((ch >> 1) & 1)
    mux_s0.value((ch >> 0) & 1)
    time.sleep_us(10)

should_exit = None

def set_exit_checker(f):
    global should_exit
    should_exit = f

# Same signal names as compute_distro (P70/P71 connector)
SIGS = {
    1: "GND7", 2: "COMP_D_GBE_P", 3: "IMU_POCI_N", 4: "COMP_D_GBE_N", 5: "IMU_POCI_P",
    6: "COMP_C_GBE_P", 7: "GND6", 8: "COMP_C_GBE_N", 9: "IMU_FSYNC_N", 10: "COMP_B_GBE_P",
    11: "IMU_FSYNC_P", 12: "COMP_B_GBE_N", 13: "GND5", 14: "COMP_A_GBE_P", 15: "GND4",
    16: "COMP_A_GBE_N", 17: "GND3", 18: "VBUS4", 19: "IMU_CS_P", 20: "VBUS3",
    21: "IMU_CS_N", 22: "VBUS2", 23: "GND2", 24: "VBUS1", 25: "IMU_PICO_N",
    26: "IMU_5V", 27: "IMU_PICO_P", 28: "IMU_CLK_P", 29: "GND1", 30: "IMU_CLK_N"
}
THR = 1.5
# Voltage divider R65=1k, R67=100k: scale ADC voltage for true MUX voltage
VDIV_SCALE = 101.0 / 100.0

def set_threshold(volts):
    global THR
    THR = float(volts)


def alias_channel(ch):
    return ch + 15 if ch <= 15 else ch - 15


MUX_TO_CH = {i: i for i in range(1, 31)}


GND_CHANNELS = {1, 7, 13, 15, 17, 23, 29}
VBUS_CHANNELS = {18, 20, 22, 24}


def should_ignore_pair(ch_a, ch_b):
    if ch_b == alias_channel(ch_a):
        return True
    if ch_a in GND_CHANNELS and ch_b in GND_CHANNELS:
        return True
    if ch_a in VBUS_CHANNELS and ch_b in VBUS_CHANNELS:
        return True
    return False


IGNORE_MUX_BY_CH = {}
for ch in range(1, 31):
    alias_ch = alias_channel(ch)
    IGNORE_MUX_BY_CH[ch] = {alias_ch}

def do_one_scan():
    shorts = {c: set() for c in range(1, 31)}
    for d in range(1, 16):
        if should_exit and should_exit():
            return None
        set_demux(d)
        for m in range(1, 16):
            if should_exit and should_exit():
                return None
            set_mux(m)
            time.sleep_ms(2)
            v0 = (adc0.read_u16() / 65535) * 3.3 * VDIV_SCALE
            v1 = (adc1.read_u16() / 65535) * 3.3 * VDIV_SCALE
            if m != d:
                if v0 >= THR:
                    if (m not in IGNORE_MUX_BY_CH.get(d, set())) and (not should_ignore_pair(d, m)):
                        shorts[d].add(m)
                        shorts[m].add(d)
                if v1 >= THR:
                    ch_lo = d + 15
                    ch_hi = m + 15
                    if (ch_hi not in IGNORE_MUX_BY_CH.get(ch_lo, set())) and (not should_ignore_pair(ch_lo, ch_hi)):
                        shorts[ch_lo].add(ch_hi)
                        shorts[ch_hi].add(ch_lo)
    out = []
    for c in range(1, 31):
        out.append({
            "channel": c,
            "signal": SIGS[c],
            "shorted_with": sorted(shorts[c])
        })
    return out

def run():
    print("Compute Distro short test started")
    while True:
        if should_exit and should_exit():
            return
        res = do_one_scan()
        if res is None:
            return
        print(json.dumps({"test_name": "Compute Distro Short Test", "channels": res}))
        time.sleep_ms(10)

if __name__ == "__main__":
    run()
