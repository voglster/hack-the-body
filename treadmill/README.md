# Treadmill bridge

ESP8266 + MAX3232 → Precor CSAFE (RJ45). The ESP8266 exposes a raw TCP
socket on the LAN; bytes flow transparently between the socket and the
RS232 link. CSAFE framing happens on the host, not on the MCU — keeps
the firmware dumb and easy to reuse for other RS232 toys.

```
[ host ] --TCP:8023--> [ ESP8266 ] --TTL UART--> [ MAX3232 ] --RS232--> [ Precor RJ45 ]
```

## Hardware

- ESP8266 board (Wemos D1 mini / NodeMCU). 3.3 V logic.
- MAX3232 breakout (the **3232**, not 232 — needs 3.3 V, has the four
  charge-pump caps on board).
- RJ45 jack or a chopped Ethernet cable to mate with the Precor CSAFE
  port.

### Wiring

Using the **Proto-Advantage ICB-MAX3232** DIP-10 breakout (datasheet:
`datasheets/ICB-MAX3232.pdf`). Pin 1 is top-left when the silkscreen
"PROTO-ADVANTAGE" reads upright; pins descend 1→5 down the left,
10→6 down the right. Channel 2 (DIP pins 3, 5, 6, 8) is unused.

| ESP8266 (D1 mini) | MAX3232 DIP pin | MAX3232 signal | Notes                    |
|-------------------|-----------------|----------------|--------------------------|
| 3V3               | **1**           | VCC            | 3.3 V, **not 5 V**       |
| GND               | **10**          | GND            | also tie to RJ45 pin 7   |
| D6 (GPIO12) TX    | **2**           | T1IN           | MCU → RS232 driver input |
| D5 (GPIO14) RX    | **4**           | R1OUT          | RS232 receiver → MCU     |

| MAX3232 DIP pin | MAX3232 signal | Precor RJ45 (CSAFE)        | RJ45 pin |
|-----------------|----------------|----------------------------|----------|
| **9**           | T1OUT          | RX (data into treadmill)   | 3        |
| **7**           | R1IN           | TX (data out of treadmill) | 4        |
| **10**          | GND            | Signal ground              | 7        |

CSAFE is 9600 8N1 per the spec. Pin 5 is a 4.75–10 V DC source the
treadmill can supply (up to 85 mA) for accessories — leave it
disconnected; the ESP is USB-powered and back-feeding it could foul
your USB rail. Pin 6 (CTS) is optional flow control, also
disconnected. Idle RS232 TX from the treadmill sits around −5 to
−12 V relative to GND — handy for a multimeter sanity check before
you plug into the MAX3232.

We use SoftwareSerial on D5/D6 so the hardware UART stays free for
USB log output during bring-up.

## Firmware

PlatformIO project under `firmware/`. The sketch:

1. Connects to WiFi (creds in `firmware/include/secrets.h` — gitignored).
2. Starts a TCP server on port 8023.
3. Pumps bytes between the socket and SoftwareSerial @ 9600 8N1.

### One-time setup

```bash
uv tool install platformio
cp firmware/include/secrets.h.example firmware/include/secrets.h
$EDITOR firmware/include/secrets.h
```

### Build / flash / monitor

```bash
cd treadmill/firmware
pio run                                  # compile
pio run -t upload                        # flash over USB
pio device monitor -b 115200             # serial debug log
```

The debug log prints the assigned IP. Note it — that's where the
host tester connects.

## Finding the bridge on the LAN

The firmware advertises itself over mDNS as
`treadmill-bridge.local` and registers a `_csafe-bridge._tcp`
service. Three ways to reach it, in order of convenience:

1. **mDNS** — `uv run bridge_client.py find` resolves
   `treadmill-bridge.local`. On Linux this needs `nss-mdns` / Avahi
   (`sudo apt install libnss-mdns avahi-utils`); macOS works out of
   the box; Windows needs Bonjour. Once it resolves you can use the
   hostname directly: `uv run bridge_client.py status treadmill-bridge.local`.
2. **Serial log** — keep the ESP USB-tethered on first boot and run
   `pio device monitor`. The log prints `[wifi] IP: 192.168.x.y`.
3. **Router DHCP table** — look up the ESP's MAC, or
   `nmap -p 8023 --open 192.168.1.0/24`.

## Host tester

Under `host/`. uv-managed; runtime is stdlib-only, pytest is a dev dep.

```bash
cd treadmill/host
uv sync                                  # one-time
uv run pytest                            # framing tests

# raw socket sanity check (typing characters round-trips to the link)
uv run bridge_client.py raw <ip>

# send a CSAFE GETSTATUS frame
uv run bridge_client.py status <ip>

# arbitrary command bytes (hex)
uv run bridge_client.py send <ip> 80
uv run bridge_client.py send <ip> a0     # GETSPEED
```

`csafe.py` has `encode()` / `decode()` for the standard 0xF1..0xF2
framing with 0xF3 escape and XOR checksum.

## Bring-up order

1. **Flash, no MAX3232 connected.** Watch the debug log for `IP: ...`.
2. **TCP only.** From the host: `nc <ip> 8023`. Connection should hold
   open. Disconnect — log says `client disconnected`.
3. **TTL loopback.** Power off, jumper ESP8266 D5↔D6 directly (skip
   the MAX3232). Power on, reconnect, type — every char should echo.
   Confirms the bridge itself works.
4. **MAX3232 loopback.** Remove the jumper, wire MAX3232 in,
   short its RS232 T1OUT↔R1IN. Type — chars should still echo.
   Confirms the level shifter + caps are good.
5. **Precor.** Plug into the CSAFE port. `bridge_client.py status`
   should return a framed response starting with `0xF1`. If you get
   nothing, swap TX/RX on the RS232 side or recheck baud rate
   (some older Precors use 4800).
