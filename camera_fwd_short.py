# Camera Flex short test: nested DEMUX/MUX scan; high on wrong MUX = short
#
# How it works:
# - We drive one cable wire at a time (DEMUX selects which wire gets driven).
# - We then scan all MUX positions (y=1..15). ADC0 reads MUX nets 1-15, ADC1 reads MUX nets 16-30.
# - If we see voltage >= THR on a MUX net that is NOT the one we're driving, we record a short
#   between our channel and any channel that uses that net.
# - So: drive channel's wire -> expect high only on that channel's mux_net. High elsewhere = short.
#
# False shorts can come from: threshold too low (noise/crosstalk), or settling time too short.
# Tweak THR (higher = stricter) or SETTLE_MS if you see incorrect shorts.
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

CHANS = [
    (4, 5, "GMSL2_PF_N"),
    (5, 22, "BLOWER_PF_A"), #
    (6, 3, "GMSL2_PF_P"),
    (7, 24, "BLOWER_PF_B"),
    (9, 26, "BLOWER_PF_C"),
    (10, 9, "V_CAM_PF"),
    (11, 25, "BLOWER_SF_C"),
    (13, 23, "BLOWER_SF_B"),
    (14, 15, "GMSL2_SF_N"),
    (15, 21, "BLOWER_SF_A"),
    (16, 13, "GMSL2_SF_P"),
    (20, 19, "V_CAM_SF"), #
]
THR = 1.5  # Volts; raise to 2.0 or 2.2 if noise causes false shorts
SETTLE_MS = 4  # Delay after set_mux before reading; increase if readings are unstable
VDIV_SCALE = 101.0 / 100.0

def set_threshold(volts):
    global THR
    THR = float(volts)

MUX_NET_TO_CH = {}
for i, (_, m_net, _) in enumerate(CHANS, 1):
    MUX_NET_TO_CH.setdefault(m_net, []).append(i)

CH_BY_DNET = {}
for i, (d_net, _, _) in enumerate(CHANS, 1):
    CH_BY_DNET.setdefault(d_net, []).append(i)

def alias_dnet(net):
    """Return the paired DEMUX net that maps to the same Y via net_to_y()."""
    return net + 15 if net <= 15 else net - 15

IGNORE_MUX_BY_CH = {}
for ch_num, (d_net, _, _) in enumerate(CHANS, 1):
    alias_net = alias_dnet(d_net)
    ignore = set()
    for alias_ch in CH_BY_DNET.get(alias_net, []):
        ignore.add(CHANS[alias_ch - 1][1])  # alias channel's mux_net
    IGNORE_MUX_BY_CH[ch_num] = ignore

def do_scan():
    shorts = {i: set() for i in range(1, len(CHANS) + 1)}
    for ch_num, (d_net, m_net, _) in enumerate(CHANS, 1):
        if should_exit and should_exit():
            return None
        ignore_mux_nets = IGNORE_MUX_BY_CH.get(ch_num, set())
        set_demux(net_to_y(d_net))
        for y in range(1, 16):
            if should_exit and should_exit():
                return None
            set_mux(y)
            time.sleep_ms(SETTLE_MS)
            raw0 = adc0.read_u16()
            raw1 = adc1.read_u16()
            v0 = (raw0 / 65535) * 3.3 * VDIV_SCALE
            v1 = (raw1 / 65535) * 3.3 * VDIV_SCALE
            # ADC0 reads nets 1-15 at MUX y=1..15. Expect high only when m_net in 1-15 and y == m_net.
            expect_high_v0 = m_net <= 15 and y == m_net
            if v0 >= THR and not expect_high_v0:
                if y in ignore_mux_nets:
                    continue
                for other in MUX_NET_TO_CH.get(y, []):
                    shorts[ch_num].add(other)
                    shorts[other].add(ch_num)
            # ADC1 reads nets 16-30 at MUX y=1..15 (net_hi = 15+y). Expect high only when m_net in 16-30 and 15+y == m_net.
            net_hi = 15 + y
            expect_high_v1 = 16 <= m_net <= 30 and m_net == net_hi
            if v1 >= THR and not expect_high_v1:
                if net_hi in ignore_mux_nets:
                    continue
                for other in MUX_NET_TO_CH.get(net_hi, []):
                    shorts[ch_num].add(other)
                    shorts[other].add(ch_num)
    return [
        {"channel": i, "signal": CHANS[i - 1][2], "shorted_with": sorted(shorts[i])}
        for i in range(1, len(CHANS) + 1)
    ]

def run():
    print("Camera Flex short test started")
    while True:
        if should_exit and should_exit():
            return
        res = do_scan()
        if res is None:
            return
        print(json.dumps({"test_name": "Camera Flex Short Test", "channels": res}))
        time.sleep_ms(10)

if __name__ == "__main__":
    run()
