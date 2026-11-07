#!/usr/bin/env python3
"""
Wake-on-LAN: включить компьютер по сети.

Запускать НЕ на самом компьютере, а на устройстве, которое включено:
телефон (Termux), другой ПК, Raspberry Pi и т.п. — в той же сети.

    python wol.py AA:BB:CC:DD:EE:FF
    python wol.py AA:BB:CC:DD:EE:FF 192.168.1.255   # свой broadcast-адрес
"""
import socket
import sys


def wake(mac, broadcast="255.255.255.255", port=9):
    mac_bytes = bytes.fromhex(mac.replace(":", "").replace("-", ""))
    if len(mac_bytes) != 6:
        raise ValueError("MAC должен состоять из 6 байт, например AA:BB:CC:DD:EE:FF")
    packet = b"\xff" * 6 + mac_bytes * 16
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        s.sendto(packet, (broadcast, port))
        s.sendto(packet, (broadcast, 7))


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    wake(sys.argv[1], *(sys.argv[2:3] or []))
    print("Магический пакет отправлен:", sys.argv[1])
