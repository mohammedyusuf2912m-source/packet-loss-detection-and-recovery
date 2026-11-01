import socket
import json
import argparse
import time
import urllib.request

parser = argparse.ArgumentParser()
parser.add_argument("--host", default="127.0.0.1")
parser.add_argument("--port", type=int, default=5001)
parser.add_argument("--count", type=int, default=20)
parser.add_argument("--timeout", type=float, default=1.0)
parser.add_argument("--retries", type=int, default=5)
parser.add_argument(
    "--controller-url",
    default="http://192.168.100.1:8080/sdn/reroute"
)
args = parser.parse_args()
def report_loss(loss_rate):
    report = {
        "loss_rate": loss_rate
    }

    try:
        request = urllib.request.Request(
            args.controller_url,
            data=json.dumps(report).encode(),
            headers={"Content-Type": "application/json"},
            method="POST"
        )

        response = urllib.request.urlopen(request, timeout=3)
        result = json.loads(response.read().decode())

        print(
            f"Controller response: "
            f"{result['active_path']} "
            f"(loss: {loss_rate * 100:.2f}%)"
        )

    except Exception as error:
        print(f"Could not report loss to controller: {error}")
sender = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sender.settimeout(args.timeout)

receiver_address = (args.host, args.port)

packets_sent = 0
packets_attempted = 0
packets_acknowledged = 0
retransmissions = 0
packets_needing_retransmission = 0
recovery_times = []

print(f"Sending {args.count} packets to "
      f"{args.host}:{args.port}")

try:
    for seq in range(1, args.count + 1):

        packets_attempted += 1

        packet = {
            "type": "DATA",
            "seq": seq,
            "payload": f"Hello from packet {seq}"
        }

        acknowledged = False
        attempts_for_packet = 0
        first_sent_at = time.monotonic()

        for attempt in range(args.retries + 1):

            sender.sendto(
                json.dumps(packet).encode(),
                receiver_address
            )

            packets_sent += 1
            attempts_for_packet += 1

            if attempt > 0:
                retransmissions += 1
                print(f"Retransmitting packet {seq}, "
                      f"attempt {attempt}")
            else:
                print(f"Sending packet {seq}")

            deadline = time.monotonic() + args.timeout

            while True:
                remaining = deadline - time.monotonic()

                if remaining <= 0:
                    break

                sender.settimeout(remaining)

                try:
                    data, address = sender.recvfrom(4096)
                    ack = json.loads(data.decode())

                    if (address == receiver_address
                            and ack.get("type") == "ACK"
                            and ack.get("seq") == seq):

                        print(f"ACK received for packet {seq}")

                        acknowledged = True
                        packets_acknowledged += 1

                        elapsed = time.monotonic() - first_sent_at

                        if attempts_for_packet > 1:
                            recovery_times.append(elapsed)
                            print(
                                f"Packet {seq} recovered in "
                                f"{elapsed:.3f} seconds "
                                f"after {attempts_for_packet - 1} "
                                f"retransmission(s)"
                            )

                        break

                except socket.timeout:
                    break

            if acknowledged:
                break

            print(f"Timeout waiting for ACK {seq}")

        if attempts_for_packet > 1:
            packets_needing_retransmission += 1
            loss_rate = (
            packets_needing_retransmission / packets_attempted)
            report_loss(loss_rate)
        if not acknowledged:
            print(f"ERROR: Packet {seq} could not be delivered.")
            print("Stopping transmission.")
            break

    finish_message = {
        "type": "FIN"
    }

    sender.sendto(
        json.dumps(finish_message).encode(),
        receiver_address
    )

except KeyboardInterrupt:
    print("\nSender interrupted.")

finally:
    sender.close()

    print("\nSender statistics")
    print("-----------------")
    print(f"Original packets attempted: {packets_attempted}")
    print(f"Total transmissions: {packets_sent}")
    print(f"Packets acknowledged: {packets_acknowledged}")
    print(f"Packets requiring retransmission: "
          f"{packets_needing_retransmission}")
    print(f"Total retransmissions: {retransmissions}")

    if packets_attempted:
        delivery_ratio = (
            packets_acknowledged / packets_attempted
        ) * 100
        print(f"Successful delivery ratio: {delivery_ratio:.2f}%")

    if packets_sent:
        retransmission_rate = (
            retransmissions / packets_sent
        ) * 100
        print(f"Retransmission rate: {retransmission_rate:.2f}%")

    if recovery_times:
        average_recovery = sum(recovery_times) / len(recovery_times)

        print(f"Successfully recovered packets: "
              f"{len(recovery_times)}")
        print(f"Average recovery time: {average_recovery:.3f} seconds")
        print(f"Maximum recovery time: "
              f"{max(recovery_times):.3f} seconds")
    else:
        print("No packets required successful retransmission.")
