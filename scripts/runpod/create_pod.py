"""
Create a RunPod GPU pod for AutoExpress's ComfyUI workflows, with the image and ports from docs/runpod.md.

    RUNPOD_API_KEY=... [JUPYTER_PASSWORD=...] python scripts/runpod/create_pod.py [--gpu "NVIDIA RTX PRO 6000 Blackwell Server Edition"] [--community]

Then open the pod's Jupyter (port 8888) or SSH in and run scripts/runpod/setup_comfyui.sh, which installs
ComfyUI and downloads the models. Pods bill until you stop them: stop or delete it in the RunPod console when done.
"""

import argparse
import json
import os
import secrets
import sys

import requests

API = "https://rest.runpod.io/v1"
IMAGE = "runpod/pytorch:2.8.0-py3.11-cuda12.8.1-cudnn-devel-ubuntu22.04"
# Tried in order. 48 GB or more keeps Wan 2.2 14B and Qwen-Image-Edit loaded together; 24 GB works with offloading.
GPUS = [
    "NVIDIA RTX PRO 6000 Blackwell Server Edition",
    "NVIDIA RTX PRO 6000 Blackwell Workstation Edition",
    "NVIDIA RTX 6000 Ada Generation",
    "NVIDIA H100 80GB HBM3",
    "NVIDIA A100 80GB PCIe",
    "NVIDIA L40S",
    "NVIDIA A40",
]


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--name", default="autoexpress-comfyui")
    parser.add_argument("--gpu", action="append", help="GPU type id to use (repeat to give fallbacks); default: a list of 48 GB+ GPUs")
    parser.add_argument("--disk", type=int, default=200, help="Container disk in GB (the models take about 80 GB)")
    parser.add_argument("--community", action="store_true", help="Community cloud instead of secure cloud (cheaper, less available)")
    args = parser.parse_args(argv)

    key = os.environ.get("RUNPOD_API_KEY")
    if not key:
        print("Set RUNPOD_API_KEY (RunPod console > Settings > API Keys).", file=sys.stderr)
        return 2
    # Jupyter's password: JUPYTER_PASSWORD if set, else a new one saved to a file only you can read (never printed).
    password = os.environ.get("JUPYTER_PASSWORD") or secrets.token_urlsafe(12)
    password_file = None
    if not os.environ.get("JUPYTER_PASSWORD"):
        password_file = os.path.abspath("runpod_jupyter_password.txt")
        descriptor = os.open(password_file, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(descriptor, "w") as handle:
            handle.write(password + "\n")
    body = {
        "name": args.name,
        "imageName": IMAGE,
        "gpuTypeIds": args.gpu or GPUS,
        "gpuCount": 1,
        "cloudType": "COMMUNITY" if args.community else "SECURE",
        "containerDiskInGb": args.disk,
        "ports": ["8888/http", "8188/http", "22/tcp"],
        "env": {"JUPYTER_PASSWORD": password},
    }
    response = requests.post(f"{API}/pods", json=body, headers={"Authorization": f"Bearer {key}"}, timeout=60)
    if response.status_code >= 400:
        print(f"RunPod refused the pod: {response.status_code} {response.text[:500]}", file=sys.stderr)
        return 1
    pod = response.json()
    pod_id = pod.get("id")
    print(json.dumps({"id": pod_id, "gpu": (pod.get("machine") or {}).get("gpuTypeId"), "cost_per_hour": pod.get("costPerHr")}, indent=2))
    where = f"saved in {password_file}" if password_file else "from JUPYTER_PASSWORD"
    print(f"Jupyter:  https://{pod_id}-8888.proxy.runpod.net  (password {where})")
    print(f"ComfyUI:  https://{pod_id}-8188.proxy.runpod.net  (after the setup script)")
    print("In a Jupyter terminal run:")
    print("  curl -fsSL https://raw.githubusercontent.com/deepratna-awale/AutoExpress/main/scripts/runpod/setup_comfyui.sh | bash")
    return 0


if __name__ == "__main__":
    sys.exit(main())
