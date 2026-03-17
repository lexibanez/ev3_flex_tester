# Hover Aft Flex short test: nested DEMUX/MUX scan; high on wrong MUX = short
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

# Same pin matching as hover_aft_flex: (demux_net, mux_net, signal_name)
CHANS = [
    (21, 23, "T1_IN_P"),
    (22, 1, "28V_SERVO"),
    (23, 21, "T1_IN_N"),
    (24, 4, "GND1_HOVAFT"),
    (25, 4, "GND2_HOVAFT"),
    (26, 2, "RS485_P"),
    (27, 22, "T1_OUT_P"),
    (28, 3, "RS485_N"),
    (29, 24, "T1_OUT_N"),
    (30, 26, "CHASSIS"),
]
THR = 1.5
VDIV_SCALE = 101.0 / 100.0

def set_threshold(volts):
    global THR
    THR = float(volts)

# mux_net -> list of channel numbers (1-based) that use that mux net (e.g. 4 -> [4, 5])
MUX_NET_TO_CH = {}
for i, (_, m_net, _) in enumerate(CHANS, 1):
    MUX_NET_TO_CH.setdefault(m_net, []).append(i)

def do_scan():
    shorts = {i: set() for i in range(1, 11)}
    for ch_num, (d_net, m_net, _) in enumerate(CHANS, 1):
        if should_exit and should_exit():
            return None
        set_demux(net_to_y(d_net))
        for y in range(1, 16):
            if should_exit and should_exit():
                return None
            set_mux(y)
            time.sleep_ms(2)
            raw0 = adc0.read_u16()
            raw1 = adc1.read_u16()
            v0 = (raw0 / 65535) * 3.3 * VDIV_SCALE
            v1 = (raw1 / 65535) * 3.3 * VDIV_SCALE
            # ADC0 at Y = net Y (1-15); ADC1 at Y = net 15+Y (16-30). Short only if wrong net is high.
            if v0 >= THR and net_to_y(m_net) != y:
                for other in MUX_NET_TO_CH.get(y, []):
                    shorts[ch_num].add(other)
                    shorts[other].add(ch_num)
            net_hi = 15 + y
            if v1 >= THR and m_net != net_hi:
                for other in MUX_NET_TO_CH.get(net_hi, []):
                    shorts[ch_num].add(other)
                    shorts[other].add(ch_num)
    return [
        {"channel": i, "signal": CHANS[i - 1][2], "shorted_with": sorted(shorts[i])}
        for i in range(1, 11)
    ]

def run():
    print("Hover Aft Flex short test started")
    while True:
        if should_exit and should_exit():
            return
        res = do_scan()
        if res is None:
            return
        print(json.dumps({"test_name": "Hover Aft Flex Short Test", "channels": res}))
        time.sleep_ms(10)

if __name__ == "__main__":
    run()
