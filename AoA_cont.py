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
adc1 = ADC(27)  # ADC0 channel

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
  
    test_channels = [
        {"channel": 10, "signal": "AirData_SCL_EXT_P"},
        {"channel": 11, "signal": "AirData_SCL_EXT_N"},
        {"channel": 12, "signal": "AirData_SDA_EXT_P"},
        {"channel": 13, "signal": "AirData_12V6"},
        {"channel": 14, "signal": "GND_AOA"},
        {"channel": 15, "signal": "AirData_SDA_EXT_N"}
    ]
    
    while True:
        # Check if we should exit (for test switching)
        if should_exit and should_exit():
            return
        
        results = []
        
        # Cycle through channels Y10 to Y15 (matching DEMUX and MUX)
        for ch_info in test_channels:
            # Check if we should exit between channels
            if should_exit and should_exit():
                return
            
            ch = ch_info["channel"]
            signal = ch_info["signal"]
            
            # Set both DEMUX and MUX to same channel
            set_demux_channel(ch)
            set_mux_channel(ch)
            
            # Allow settling time (same as jumpertest)
            time.sleep_ms(2)
            
            # Read voltage from ADC0
            raw_value = adc1.read_u16()
            voltage = (raw_value / 65535) * 3.3 * VDIV_SCALE
            
            # Determine status (threshold: 1.5V for continuity test - same as jumpertest)
            status = "PASS" if voltage >= 1.5 else "FAIL"
            
            results.append({
                "channel": ch,
                "signal": signal,
                "voltage": round(voltage, 3),
                "status": status
            })
        
        # Send JSON data for GUI (standardized format)
        # Format: {"test_name": "Test Name", "channels": [{"channel": N, "signal": "SignalName", "voltage": V, "status": "PASS/FAIL"}]}
        print(json.dumps({
            "test_name": "AoA/Pitot Flex Continuity Test",
            "channels": results
        }))
        
        # Delay between full cycles (same as jumpertest)
        time.sleep_ms(10)

# Only run if executed directly (not when imported)
if __name__ == "__main__":
    run()
