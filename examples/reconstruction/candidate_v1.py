"""Independent reconstruction from the supplied native-parcel packet.

Run with Python; commands arrive on stdin and responses are JSON lines.
No persistent files or dependencies are used.
"""

import json
import os
import sys


_C_SPACE = b" \t\n\r\v\f"


def input_chunks(stream):
    """Model text-mode fgets(buffer, 128, input) on the observed Windows target."""
    chunk = bytearray()
    pending = b""
    while True:
        byte = pending or stream.read(1)
        pending = b""
        if byte == b"\r":
            following = stream.read(1)
            if following == b"\n":
                byte = b"\n"
            else:
                pending = following
        if not byte or byte == b"\x1a":
            if chunk:
                yield bytes(chunk)
            return
        chunk.extend(byte)
        if byte == b"\n" or len(chunk) == 127:
            yield bytes(chunk)
            chunk.clear()


def skip_space(data, position):
    while position < len(data) and data[position] in _C_SPACE:
        position += 1
    return position


def scan_decimal(data, position):
    """Scan one decimal %d prefix, storing its signed 32-bit result."""
    position = skip_space(data, position)
    sign = 1
    if position < len(data) and data[position] in b"+-":
        if data[position] == ord("-"):
            sign = -1
        position += 1
    start = position
    value = 0
    while position < len(data) and ord("0") <= data[position] <= ord("9"):
        value = (value * 10 + data[position] - ord("0")) & 0xFFFFFFFF
        position += 1
    if position == start:
        return None, position
    value = (sign * value) & 0xFFFFFFFF
    if value >= 0x80000000:
        value -= 0x100000000
    return value, position


def parse_command(chunk):
    """Reconstruct the bounded verb and two sequential scanf assignments.

    Both numeric locals are cleared before each call. A failed numeric
    conversion stops scanning, not dispatch; trailing input is ignored.
    """
    data = chunk.split(b"\0", 1)[0]
    position = skip_space(data, 0)
    if position == len(data):
        return None
    start = position
    while (position < len(data) and position - start < 31
           and data[position] not in _C_SPACE):
        position += 1
    verb = data[start:position]
    a = b = 0
    parsed_a, position = scan_decimal(data, position)
    if parsed_a is not None:
        a = parsed_a
        parsed_b, position = scan_decimal(data, position)
        if parsed_b is not None:
            b = parsed_b
    return verb, a, b


class ParcelProtocol:
    def __init__(self, zone=0):
        self.available = 12
        self.reserved = 0
        self.zone = zone

    def state(self):
        return {"ok": True, "available": self.available,
                "reserved": self.reserved}

    @staticmethod
    def error(reason):
        return {"ok": False, "error": reason}

    def dispatch(self, verb, a=0, b=0):
        if verb == b"quote":
            if not 1 <= a <= 20000 or b not in (0, 1):
                return self.error("weight-or-priority")
            steps = (a + 499) // 500
            cents = 250 + steps * 75
            if self.zone == 2:
                cents += 180
            if b:
                cents += 300 + steps * 20
            return {"ok": True, "cents": cents, "zone": self.zone}
        if verb == b"reserve":
            if not 1 <= a <= self.available:
                return self.error("stock")
            self.available -= a
            self.reserved += a
            return self.state()
        if verb == b"cancel":
            if not 1 <= a <= self.reserved:
                return self.error("reservation")
            self.available += a
            self.reserved -= a
            return self.state()
        if verb == b"state":
            return self.state()
        return self.error("operation")


def main():
    zone = 2 if os.environ.get("TRACEANCHOR_PARCEL_ZONE") == "remote" else 0
    protocol = ParcelProtocol(zone)
    for chunk in input_chunks(sys.stdin.buffer):
        command = parse_command(chunk)
        if command is not None:
            response = protocol.dispatch(*command)
            encoded = json.dumps(response, separators=(",", ":")).encode("ascii")
            sys.stdout.buffer.write(encoded + b"\r\n")
            sys.stdout.buffer.flush()
    # main ignores per-command failure codes and returns zero after EOF.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
