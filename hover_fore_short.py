# Hover Fore Flex short test: nested DEMUX/MUX scan; high on wrong MUX = short
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

# Same pin matching as hover_fore_flex: (demux_net, mux_net, signal_name)
CHANS = [
    (1, 4, "T1_IN_P"),
    (3, 2, "T1_IN_N"),
    (7, 1, "T1_OUT_P"),
    (9, 3, "T1_OUT_N"),
    (10, 6, "CHASSIS"),
]
THR = 1.5
VDIV_SCALE = 101.0 / 100.0

def set_threshold(volts):
    global THR
    THR = float(volts)

# MUX net -> channel number (only our 5 MUXs)
MUX_TO_CH = {m: i for i, (_, m, _) in enumerate(CHANS, 1)}

def do_scan():
    shorts = {i: set() for i in range(1, 6)}
    for ch_num, (d_net, m_net, _) in enumerate(CHANS, 1):
        if should_exit and should_exit():
            return None
        set_demux(net_to_y(d_net))
        for m in range(1, 16):
            if should_exit and should_exit():
                return None
            set_mux(net_to_y(m))
            time.sleep_ms(2)
            raw = adc0.read_u16()
            v = (raw / 65535) * 3.3 * VDIV_SCALE
            if m != m_net and v >= THR:
                if m in MUX_TO_CH:
                    other = MUX_TO_CH[m]
                    shorts[ch_num].add(other)
                    shorts[other].add(ch_num)
    return [
        {"channel": i, "signal": CHANS[i - 1][2], "shorted_with": sorted(shorts[i])}
        for i in range(1, 6)
    ]

def run():
    print("Hover Fore Flex short test started")
    while True:
        if should_exit and should_exit():
            return
        res = do_scan()
        if res is None:
            return
        print(json.dumps({"test_name": "Hover Fore Flex Short Test", "channels": res}))
        time.sleep_ms(10)

if __name__ == "__main__":
    run()
