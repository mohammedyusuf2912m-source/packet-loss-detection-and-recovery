# Packet Loss Detection and Recovery Using SDN

## 1. Project Overview

This project implements a UDP-based packet loss detection and recovery system using Software-Defined Networking (SDN).

UDP does not guarantee packet delivery. This project addresses that limitation by implementing sequence numbers, acknowledgements, timeout detection and retransmission.

A Ryu SDN controller monitors packet loss reported by the sender and dynamically switches traffic between primary and backup network paths.

## 2. Objectives

- Detect packet loss during UDP communication.
- Recover lost packets through retransmission.
- Monitor packet delivery and recovery statistics.
- Dynamically reroute traffic using an SDN controller.
- Maintain connectivity when the primary network link fails.
- Evaluate the system under different packet loss conditions.

## 3. Technologies Used

- Python 3
- UDP Socket Programming
- Mininet
- Open vSwitch (OVS)
- Ryu SDN Controller
- OpenFlow 1.3
- Linux Ubuntu
- Traffic Control (`tc netem`)
- Git and GitHub

## 4. System Architecture

The network contains two hosts and four OpenFlow switches.

```text
                  PRIMARY PATH
             S1 -------- S2
            /              \
           /                \
         H1                  S4 -------- H2
           \                /
            \              /
             S1 -------- S3
                  BACKUP PATH
```

Logical topology:

```text
             S1 ---- S2
            /          \
           /            \
         H1              S4 ---- H2
           \            /
            \          /
             S1 ---- S3
```

The actual connections are:

- Primary: H1 → S1 → S2 → S4 → H2
- Backup: H1 → S1 → S3 → S4 → H2

The Ryu controller manages forwarding rules using OpenFlow 1.3.

## 5. Project Structure

```text
packet-loss-recovery/
│
├── reroute_controller.py
├── reroute_controller_before_api.py
├── topology.py
│
├── udp_application/
│   ├── sender.py
│   └── receiver.py
│
├── mininet/
│   ├── experiments.py
│   ├── network_config.py
│   ├── topology.py
│   └── results/
│       ├── final_experiment_results.csv
│       ├── baseline-0-sender.log
│       ├── baseline-0-receiver.log
│       ├── loss-5-sender.log
│       ├── loss-5-receiver.log
│       ├── loss-10-sender.log
│       ├── loss-10-receiver.log
│       ├── loss-20-sender.log
│       └── loss-20-receiver.log
│
└── README.md
```

## 6. How It Works

### UDP Sender

The sender:

1. Creates UDP packets containing sequence numbers.
2. Sends packets to the receiver.
3. Waits for acknowledgements.
4. Detects missing acknowledgements through timeouts.
5. Retransmits packets when necessary.
6. Calculates delivery and retransmission statistics.
7. Reports the observed retransmission-needed ratio to the Ryu controller.

### UDP Receiver

The receiver:

1. Receives UDP packets.
2. Identifies packets using sequence numbers.
3. Sends acknowledgements to the sender.
4. Supports deterministic packet-drop simulation for testing.

### SDN Controller

The Ryu controller:

- Installs primary and backup forwarding rules.
- Receives packet loss reports through a REST API.
- Uses a configured threshold of 5% to decide whether to switch paths.
- Monitors primary-path port failures.
- Restores the primary route when the failed ports become operational again.

REST endpoint:

```text
POST http://<controller-ip>:8080/sdn/reroute
```

The controller uses OpenFlow 1.3 and listens on TCP port 6653.

## 7. Running the Project

### Requirements

- Ubuntu Linux
- Python 3
- Mininet
- Open vSwitch
- Ryu SDN Controller

The tested setup used Ryu 4.35 with Python 3.12 in a virtual environment.

### Step 1: Start the Ryu Controller

Open a terminal:

```bash
cd ~/packet-loss-recovery
source ~/ryu-env/bin/activate

ryu-manager --ofp-tcp-listen-port 6653 reroute_controller.py
```

Keep this terminal running.

### Step 2: Run the Mininet Experiment

Open another terminal:

```bash
cd ~/packet-loss-recovery/mininet
```

Example experiment with 5% configured random packet loss:

```bash
sudo python3 experiments.py \
--controller-ip 127.0.0.1 \
--loss 5 \
--duration 60 \
--receiver-command "python3 /home/md-yousuf/packet-loss-recovery/udp_application/receiver.py --port 5001 --drop-every 0" \
--sender-command "python3 /home/md-yousuf/packet-loss-recovery/udp_application/sender.py --host 10.0.0.2 --port 5001 --count 20" \
--output results/loss-5.csv
```

Change `--loss` to experiment with different configured random packet loss percentages.

For example:

```text
--loss 0
--loss 5
--loss 10
--loss 20
```

The experiment runner configures the network impairment, starts the applications, collects logs and saves experiment metadata.

### Step 3: Simulate Deterministic Packet Drops

To simulate an application-level packet drop every fourth packet, change the receiver command to:

```bash
python3 /home/md-yousuf/packet-loss-recovery/udp_application/receiver.py --port 5001 --drop-every 4
```

This provides a controlled way to test retransmission and recovery.

Note: deterministic receiver-side drops are different from random link-level packet loss configured through `tc netem`.

## 8. Physical Link Failure Testing

The project also supports testing SDN failover when the primary link physically fails.

Start the Ryu controller, then launch the interactive topology:

```bash
cd ~/packet-loss-recovery
sudo python3 topology.py
```

Inside the Mininet CLI:

Check normal connectivity:

```text
pingall
```

Disable the primary link:

```text
link s1 s2 down
```

Test connectivity again:

```text
pingall
```

Restore the primary link:

```text
link s1 s2 up
```

Test connectivity:

```text
pingall
```

The controller detects the port status change and installs the appropriate forwarding rules.

## 9. Experimental Results

Twenty packets were sent in each random-loss experiment.

| Configured random loss | Packets sent | Total transmissions | Retransmissions | Delivery ratio |
|---|---:|---:|---:|---:|
| 0% | 20 | 20 | 0 | 100% |
| 5% | 20 | 21 | 1 | 100% |
| 10% | 20 | 20 | 0 | 100% |
| 20% | 20 | 20 | 0 | 100% |

The 5% experiment recovered one packet through retransmission, with an average recovery time of approximately 1.002 seconds.

The 10% and 20% experiments did not observe packet loss in their respective 20-packet samples. Configured random loss does not guarantee that a packet will be dropped in every short experiment.

### Additional Recovery Test

A deterministic packet-drop test was also performed using `--drop-every 4`.

In a successful 20-packet test:

- Original packets sent: 20
- Packets requiring retransmission: 5
- Total transmissions: 25
- Packets acknowledged: 20
- Delivery ratio: 100%
- Average recovery time: approximately 1.002 seconds

This demonstrated successful recovery of deliberately dropped packets.

### Physical Failover Test

The primary link between S1 and S2 was disabled.

Observed results:

- The controller detected the primary-path failure.
- Traffic was redirected through S1 → S3 → S4.
- Connectivity was maintained during the failure.
- The primary route was restored after the link came back up.

## 10. Results and Logs

Experiment results are stored in:

```text
mininet/results/
```

The consolidated metrics are available in:

```text
mininet/results/final_experiment_results.csv
```

Individual sender and receiver logs are also preserved for verification.

## 11. Limitations

- Random packet loss is probabilistic; short experiments may not observe the configured loss percentage.
- The controller's loss decision uses the retransmission-needed ratio reported by the sender, which can fluctuate with small packet samples.
- The current implementation uses a fixed loss threshold rather than adaptive threshold selection.

## 12. Future Improvements

- Evaluate performance using larger packet counts.
- Compare different retransmission timeout strategies.
- Implement adaptive loss thresholds.
- Measure end-to-end latency and throughput.
- Extend testing to larger network topologies.
- Compare recovery performance across different SDN routing strategies.
