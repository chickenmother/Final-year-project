import json
import sys

path = sys.argv[1]
with open(path, encoding="utf-8") as handle:
    report = json.load(handle)
print(json.dumps(report.get("summary"), indent=1))
env = report.get("environment") or {}
for key in ("placement", "placement_table", "mode_final", "crossings",
            "stream_tier", "pixels_format", "stalls", "encode_fps",
            "stage_p50", "stage_p50_x", "channels", "channels_x", "chain"):
    if key in env:
        print(f"{key}: {json.dumps(env[key])}")
