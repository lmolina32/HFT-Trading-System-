#!/usr/bin/env python3

from __future__ import annotations

import socket
import struct


def create_multicast_socket(
    mcast_addr: str, mcast_port: int, local_ip: str
) -> socket.socket:
    """
    Create and configure a multicast socket.

    Args:
        mcast_addr: Multicast group address (e.g., '239.0.0.1')
        mcast_port: Multicast port (e.g., 12345)
        local_ip: Local interface IP address

    Returns:
        Configured socket object
    """
    # Create UDP socket
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)

    # Set socket options
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 4 * 1024 * 1024)

    # On some systems, SO_REUSEPORT is available
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
    except AttributeError:
        pass  # SO_REUSEPORT not available on this system

    # Set socket to non-blocking
    sock.setblocking(False)

    # Bind to the multicast group
    sock.bind((mcast_addr, mcast_port))

    # Join the multicast group
    mreq = struct.pack("4s4s", socket.inet_aton(mcast_addr), socket.inet_aton(local_ip))
    sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)

    return sock
