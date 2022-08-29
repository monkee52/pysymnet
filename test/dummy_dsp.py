import select
import socket


def create_dummy_dsp():
    server = socket.socket(
        socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP
    )

    server.bind(("", 48631))
    server.listen(5)

    bind = server.getsockname()

    server2 = socket.socket(
        socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP
    )

    server2.bind(("", 48631))
    server2_clients = set()

    print(f"Listening on {bind[0]}:{bind[1]} (TCP/UDP)")

    clients = {}
    params = {}

    try:
        while True:
            rc, _, _ = select.select(
                [server, server2] + [client for client in clients], [], []
            )

            for sock in rc:
                is_udp = False
                addr = None

                def send(data: bytes) -> None:
                    nonlocal is_udp, addr

                    if is_udp:
                        server2.sendto(data, addr)
                    else:
                        sock.send(data)

                if sock == server:
                    client, addr = server.accept()

                    print(f"connection from {addr[0]}:{addr[1]}")

                    clients[client] = addr
                else:
                    lines = None

                    if sock == server2:
                        is_udp = True

                        lines, addr = server2.recvfrom(4096)

                        client = socket.socket(
                            socket.AF_INET,
                            socket.SOCK_DGRAM,
                            socket.IPPROTO_UDP
                        )

                        server2_clients.add(addr)
                    else:
                        lines = sock.recv(4096)

                    print(lines.decode())

                    if lines == b"":
                        if not is_udp:
                            del clients[sock]

                        continue

                    lines = lines.split(b"\r")[:-1]

                    for line in lines:
                        line = line.decode()

                        if line.upper() == "$V V":
                            print("get version")

                            send("Dummy DSP\r>\r".encode())
                            continue
                        else:
                            line = line.split(" ")

                        line[0] = line[0].upper()

                        match line[0]:
                            case "GS":
                                rcn = int(line[1])
                                val = params[rcn] if rcn in params else -1

                                print(f"get {rcn} = {val}")

                                send(f"{val}\r".encode())
                            case "CS":
                                rcn = int(line[1])
                                val = int(line[2])

                                params[rcn] = val

                                print(f"set {rcn} = {val}")

                                for client in clients:
                                    client.send(f"#{rcn}={val}\r".encode())
                                
                                for addr2 in server2_clients:
                                    server2.sendto(f"#{rcn}={val}\r".encode(), addr2)

                                send(b"ACK\r")
                            case "CSQ":
                                rcn = int(line[1])
                                val = int(line[2])

                                params[rcn] = val

                                print(f"set {rcn} = {val}")

                                for client in clients:
                                    client.send(f"#{rcn}={val}\r".encode())
                                
                                for addr2 in server2_clients:
                                    server2.sendto(f"#{rcn}={val}\r".encode(), addr2)

                                send(b"ACK\r")
                            case "RI":
                                ip = server.getsockname()[0]

                                print(f"ip = {ip}")

                                send(f"{ip}\r".encode())
                            case _:
                                send(f"ACK\r".encode())
    except KeyboardInterrupt:
        server.close()
        server2.close()


if __name__ == "__main__":
    print("Dummy DSP v1")

    create_dummy_dsp()
