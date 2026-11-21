FYP LATENCY NOTES — Wi-Fi vs Ethernet and threshold calibration
Last updated: 2026-11-10 14:40 +09:00

Test bed
  Cloud X : chicken-mother (remote; reached over the Internet/Tailscale)
  Middle Y: andoryuuuspc, lab Ethernet 133.17.164.245/25
  End Z   : pc23-148d, lab Ethernet 133.17.164.244/25
  Ports   : X 8001 (Y -> X), Y 8000 (Z -> Y), Y 8002 (dashboard)

--------------------------------------------------------------------
1. WHY USING WI-FI CAUSED THE PROBLEM
--------------------------------------------------------------------
Wi-Fi as a medium is not inherently the problem. The problem was the
lab access point's policy and the resulting Tailscale fallback.

Observed with both Y and Z on the lab Wi-Fi:
  - Y and Z had addresses in the same 172.19.0.0/16 subnet
    (Y 172.19.74.108, Z 172.19.74.140).
  - Despite being on the same subnet, Y could not ARP or ping Z.
    This is the signature of client/AP isolation: the access point
    forwards each client's traffic to the Internet but not to other
    clients on the same SSID.
  - Tailscale could not establish a direct WireGuard path, so it fell
    back to DERP (Tokyo, "tok"). `tailscale ping` reported
    "via DERP(tok)" and "direct connection not established".
  - DERP added a relay hop (~48-227 ms for small pings) and, more
    importantly, it is not designed for sustained high-bitrate video.
    The X stream was 960x540 JPEG q80, about 20 Mbps; when that was
    pushed through DERP, the relay queued the video. Z<->Y RTT rose to
    440-690 ms and input->display to 540-850 ms.
  - The Y fallback JPEG stream was already lower bitrate (~1.94 Mbps
    at 480x270 q40, 30 fps), but the Z<->Y RTT still had a ~60 ms
    floor because DERP was the path.
  - The lab Wi-Fi profile was also reported as Public, while the
    firewall rule "FYP Edge Y 8000 8002" is Private-only. This
    compounded the problem: direct LAN connections were blocked even
    when the AP allowed them.

Conclusion: the Wi-Fi hop was not slow because of Wi-Fi radio speed.
It was slow because client isolation prevented a direct Z<->Y path,
so Tailscale relayed the stream through DERP. DERP is a connectivity
fallback, not a high-throughput video transport; its relay queue and
TCP/TLS behaviour produced the large latency spikes.

--------------------------------------------------------------------
2. WHY ETHERNET SOLVED IT
--------------------------------------------------------------------
Connecting Y and Z to the lab Ethernet created a direct Layer-2 path
with no access point and no client isolation.

Verified addresses and connectivity:
  Y Ethernet : 133.17.164.245 /25
  Z Ethernet : 133.17.164.244 /25
  Subnet     : 133.17.164.128/25 (same L2 segment)
  From Z:
    Test-NetConnection 133.17.164.245 -Port 8000 -> True
    Test-NetConnection 133.17.164.245 -Port 8002 -> True

Result with the application:
  - Z -> Y uses the Ethernet address 133.17.164.245, not Tailscale
    and not 127.0.0.1.
  - `rtt_zy` dropped from ~56-67 ms (DERP) to ~2-4 ms (Ethernet).
  - In EDGE Y mode, input->display is under 50 ms.
  - In CLOUD X mode, input->display is ~70-80 ms; the remaining cost is
    the X<->Y path plus X render/encode, not the Z<->Y hop.
  - Tailscale is still useful for X<->Y, but it is no longer needed for
    the Z<->Y hop. The direct Ethernet path avoids DERP entirely.

Why this matters for the project: the edge tier is only effective when
Y is actually near Z. Ethernet restored that "near Z" condition. The
same application and codec produced much lower latency simply because
the last hop became direct.

--------------------------------------------------------------------
3. HOW THE THRESHOLDS WERE DECIDED
--------------------------------------------------------------------
The mode switch uses the X<->Y RTT measured by Y:
  HIGH_MS    : RTT above this counts as a bad sample (switch X -> Y)
  LOW_MS     : RTT below this allows recovery (switch Y -> X)
  BAD_COUNT  : consecutive bad samples needed to switch to Y
  RECOVER_S  : time below LOW_MS needed to return to X

The defaults (HIGH_MS=80, LOW_MS=50) are calibrated for a clean LAN
with a sub-5 ms baseline. They are not valid for this deployment.

Measured X<->Y RTT distribution from log_y.csv (slider at 0):
  p50 = 57.5 ms
  p75 = 63.0 ms
  p90 = 74.4 ms
  p95 = 92.5 ms
  p99 = 168.5 ms

With the defaults, 264 of 3424 samples were above 80 ms, and the log
showed 20+ X<->Y transitions. The system was flapping because:
  - HIGH_MS=80 is below p95, so normal X-side spikes crossed it;
  - LOW_MS=50 is below p50, so recovery was marginal and depended on
    brief dips.

Recommended thresholds for this network:
  FYP_HIGH_MS   = 110
  FYP_LOW_MS    = 75
  FYP_BAD_COUNT = 5
  FYP_RECOVER_S = 3.0

Rationale:
  - HIGH_MS=110 is above p95 (92.5) but below the p99 spikes. It still
    detects sustained degradation, while ignoring most single-sample
    noise.
  - BAD_COUNT=5 requires about 1 s of bad RTT (5 samples at 0.2 s), so a
    brief spike does not trigger a switch.
  - LOW_MS=75 is above p50/p75, so Y can recover to X after 3 s once the
    link is genuinely good again.
  - RECOVER_S=3.0 keeps the mode stable; it prevents rapid flipping.
  - If the link still flaps, raise HIGH_MS to 120 or BAD_COUNT to 7.

Run Y with these values:
  $env:FYP_HIGH_MS   = "110"
  $env:FYP_LOW_MS    = "75"
  $env:FYP_BAD_COUNT = "5"
  $env:FYP_RECOVER_S = "3.0"
  .\run_y.cmd chicken-mother

Important:
  - Thresholds are topology-specific. Recalibrate whenever the path
    changes (Wi-Fi vs Ethernet, direct vs DERP, different lab).
  - Record the measured p50/p95 and the chosen thresholds in every
    experiment run so the switching behaviour is reproducible.
  - To force a fallback for demonstration, move the dashboard slider
    above HIGH_MS. Do not rely on random RTT spikes to trigger it.
  - At slider 0 with the tuned thresholds, the system should stay in
    CLOUD X most of the time and switch to EDGE Y only during sustained
    degradation.

--------------------------------------------------------------------
4. SUMMARY FOR THE REPORT
--------------------------------------------------------------------
  - Wi-Fi + client isolation -> no direct Z<->Y path -> Tailscale DERP.
  - DERP relayed a 20 Mbps JPEG stream -> queueing and 440-690 ms
    Z<->Y latency.
  - Ethernet gave a direct 133.17.164.128/25 link -> rtt_zy ~2-4 ms.
  - EDGE Y input->display is now under 50 ms; CLOUD X is ~70-80 ms.
  - Default thresholds (80/50) are too tight for a ~58 ms baseline and
    caused flapping; 110/75 with BAD_COUNT=5 and RECOVER_S=3 is stable.
  - The edge benefit is real only when Y is near Z. Relay fallback is a
    valid experimental condition, but it is not an edge-local one.


