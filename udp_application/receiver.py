import socket
import json
import argparse

parser = argparse.ArgumentParser()
parser.add_argument("--port", type=int, default=5001)
parser.add_argument("--drop-every", type=int, default=0)
args = parser.parse_args()

receiver = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
receiver.bind(("0.0.0.0", args.port))

expected_seq = 1
received_packets = 0
simulated_losses = 0
dropped_sequences = set()

print(f"Receiver listening on port {args.port}")

if args.drop_every:
    print(f"Simulation: dropping first transmission of every "
          f"{args.drop_every}th packet")

try:
    while True:
        data, address = receiver.recvfrom(4096)
        message = json.loads(data.decode())

        packet_type = message["type"]

        # Handle termination
        if packet_type == "FIN":
            print("\nSender finished transmission.")
            break

        # Process data packets
        if packet_type == "DATA":
            seq = message["seq"]

            # Simulate packet loss for testing
            if (args.drop_every > 0
                    and seq % args.drop_every == 0
                    and seq not in dropped_sequences):

                dropped_sequences.add(seq)
                simulated_losses += 1

                print(f"SIMULATED LOSS: Packet {seq} dropped")
                continue

            if seq == expected_seq:
                print(f"Received packet {seq}: {message['payload']}")

                received_packets += 1
                expected_seq += 1

            elif seq < expected_seq:
                # Already received this packet.
                # It may have been retransmitted because its ACK was lost.
                print(f"Duplicate packet {seq} received")

            else:
                # A gap indicates missing sequence numbers.
                print(f"Missing packet(s): {expected_seq} to {seq - 1}")

            # Acknowledge the packet
            ack = {
                "type": "ACK",
                "seq": seq
            }

            receiver.sendto(
                json.dumps(ack).encode(),
                address
            )

            print(f"ACK sent for packet {seq}")

except KeyboardInterrupt:
    print("\nReceiver stopped manually.")

finally:
    print("\nReceiver statistics")
    print("-------------------")
    print(f"Packets delivered: {received_packets}")
    print(f"Simulated packet drops: {simulated_losses}")

    receiver.close()
