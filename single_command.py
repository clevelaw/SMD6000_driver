import serial
import time
import io

PORT = "COM6"
# 9600, **19200, 38400, 57600, 115200
BAUD = 9600


def dump_bytes(data):
    print(f"\n--- RAW ({len(data)} bytes) ---")
    print(data)
    print("--- HEX ---")
    print(" ".join(f"{b:02X}" for b in data))
    print("--- ASCII ---")
    print(data.decode("ascii", errors="replace"))
    print("------------------------\n")


def main():
    try:
        ser = serial.Serial(
            port=PORT,
            baudrate=BAUD,
            bytesize=serial.EIGHTBITS,
            parity=serial.PARITY_NONE,
            stopbits=serial.STOPBITS_ONE,
            timeout=1,
            xonxoff=False,
            rtscts=False,
            dsrdtr=False
        )
        serial_port = io.TextIOWrapper(io.BufferedRWPair(ser, ser,),
                                       encoding='ascii',
                                       errors='ignore')

    except Exception as e:
        print("Failed to open port:", e)
        return

    print(f"Opened {PORT} @ {BAUD}")
    time.sleep(2)

    while True:
        cmd = 'DUMP '
        ser.reset_input_buffer()
        ser.reset_output_buffer()
        tx = (cmd + '\r')
        print(f"\nSending: {tx}")
        serial_port.write(tx)
        serial_port.flush()
        data = serial_port.readline()
        print(f"---Data form read:{data}----")
        time.sleep(5)
        return


if __name__ == "__main__":
    main()
