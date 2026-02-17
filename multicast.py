#!/usr/bin/env python3

import socket
import struct
import sys
import select

def create_multicast_socket(mcast_addr, mcast_port, local_ip):
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
    mreq = struct.pack('4s4s',
                       socket.inet_aton(mcast_addr),
                       socket.inet_aton(local_ip))
    sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)

    return sock

def main():
    if len(sys.argv) < 4 or (len(sys.argv) - 2) % 2 != 0:
        print(f"Usage: {sys.argv[0]} (<mcast_addr> <mcast_port>)+ <local_ip>")
        print("Example: python script.py 239.0.0.1 12345 239.0.0.2 12345 192.168.1.100")
        sys.exit(1)

    # Parse command line arguments
    local_ip = sys.argv[-1]
    mcast_sockets = []

    # Create sockets for each multicast group
    for i in range(1, len(sys.argv) - 1, 2):
        mcast_addr = sys.argv[i]
        mcast_port = int(sys.argv[i + 1])

        try:
            sock = create_multicast_socket(mcast_addr, mcast_port, local_ip)
            mcast_sockets.append(sock)
            print(f"Subscribed to {mcast_addr}:{mcast_port}")
        except Exception as e:
            print(f"Failed to create socket for {mcast_addr}:{mcast_port}: {e}")
            sys.exit(1)

    # Create epoll object (or use select/poll as fallback)
    try:
        poller = select.epoll()
        use_epoll = True
        for sock in mcast_sockets:
            poller.register(sock.fileno(), select.EPOLLIN)
    except AttributeError:
        # epoll not available (e.g., on macOS), use select instead
        use_epoll = False
        print("epoll not available, using select()")

    print("Listening for multicast data...")

    # Main event loop
    try:
        while True:
            if use_epoll:
                # Use epoll
                events = poller.poll(timeout=0)  # Non-blocking poll

                for fd, event in events:
                    if event & select.EPOLLIN:
                        # Find the socket corresponding to this fd
                        for sock in mcast_sockets:
                            if sock.fileno() == fd:
                                try:
                                    data = sock.recv(1500)
                                    if data:
                                        #print(f"Read {len(data)} bytes")
                                        # Print hex dump
                                        hex_str = ':'.join(f'{b:02x}' for b in data)
                                        print(hex_str)
                                except BlockingIOError:
                                    pass  # No data available
                                break
            else:
                # Use select as fallback
                readable, _, _ = select.select(mcast_sockets, [], [], 0)

                for sock in readable:
                    try:
                        data = sock.recv(1500)
                        if data:
                            print(f"Read {len(data)} bytes")
                            # Print hex dump
                            hex_str = ':'.join(f'{b:02x}' for b in data)
                            print(hex_str)
                    except BlockingIOError:
                        pass  # No data available

    except KeyboardInterrupt:
        print("\nShutting down...")
    finally:
        # Clean up
        if use_epoll:
            poller.close()
        for sock in mcast_sockets:
            sock.close()

if __name__ == '__main__':
    main()
