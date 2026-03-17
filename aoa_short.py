# AoA/Pitot short test: nested DEMUX/MUX scan; high on wrong MUX = short
# Channels 10-15 only; same pins as AoA_cont
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

VDIV_SCALE = 101.0 / 100.0
THR = 1.5

def set_threshold(volts):
    global THR
    THR = float(volts)

# Channel number -> (demux_y, mux_y, signal) for AoA channels 10-15
CHANS = [
    (10, "AirData_SCL_EXT_P"),
    (11, "AirData_SCL_EXT_N"),
    (12, "AirData_SDA_EXT_P"),
    (13, "AirData_12V6"),
    (14, "GND_AOA"),
    (15, "AirData_SDA_EXT_N"),
]

def do_scan():
    shorts = {ch: set() for ch, _ in CHANS}
    for ch, _ in CHANS:
        if should_exit and should_exit():
            return None
        set_demux(ch)
        for m in range(10, 16):
            if should_exit and should_exit():
                return None
            set_mux(m)
            time.sleep_ms(2)
            raw = adc1.read_u16()
            v = (raw / 65535) * 3.3 * VDIV_SCALE
            if m != ch and v >= THR:
                shorts[ch].add(m)
                shorts[m].add(ch)
    return [
        {"channel": ch, "signal": sig, "shorted_with": sorted(shorts[ch])}
        for ch, sig in CHANS
    ]

def run():
    print("AoA/Pitot short test started")
    while True:
        if should_exit and should_exit():
            return
        res = do_scan()
        if res is None:
            return
        print(json.dumps({"test_name": "AoA/Pitot Short Test", "channels": res}))
        time.sleep_ms(10)

if __name__ == "__main__":
    run()
