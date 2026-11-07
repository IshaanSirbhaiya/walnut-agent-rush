#!/usr/bin/env python3
"""Provision Walnut's Vultr infrastructure through the Vultr API v2: a firewall group and one Cloud Compute VM.

This is the scripted alternative to clicking through the Vultr console (deploy/vultr/README.md, section 2).
It creates, in order:

  1. a firewall group ``walnut-demo-web``: TCP 22 from YOUR current IP only, TCP 80 and 443 from anywhere
     (Let's Encrypt needs 80);
  2. your SSH public key, if no key with that name exists yet;
  3. one Cloud Compute VM: Ubuntu 24.04 LTS x64, region ``sgp`` (Singapore), plan ``vc2-2c-4gb``
     (2 vCPU / 4 GB), attached to the firewall group, with deploy/vultr/cloud-init.yaml as user-data
     (REPO_URL filled in), so the stack deploys itself on first boot;
  4. then it waits for the VM's public IPv4 and prints the URL: https://<ip-with-dashes>.sslip.io

**Dry run by default.** Without ``--apply`` it only prints the requests it would send (the key is never
printed). With ``--apply`` it needs ``VULTR_API_KEY`` in the environment (Vultr console -> Account -> API:
enable the API and add your IP under Access Control, or every call answers 401). Nothing stores the key.
It refuses to run when an instance with the same label exists, so a retry cannot start a second billed VM.

  python deploy/vultr/provision.py --repo-url https://github.com/<you>/<repo>.git --ssh-key ~/.ssh/walnut_vultr.pub
  VULTR_API_KEY=... python deploy/vultr/provision.py --repo-url ... --ssh-key ... --apply

Region, plan and image can be changed with --region, --plan, --os-name. Standard library only.
Every field was checked against Vultr's published client (vultr/govultr) and the public /v2/os and /v2/plans;
not yet run against a live account (no account at the time of writing). Billing: the VM is charged hourly until you destroy it (``--destroy <instance-id>``).
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable, Optional

API = "https://api.vultr.com/v2"
HERE = Path(__file__).resolve().parent
CLOUD_INIT = HERE / "cloud-init.yaml"


class VultrError(Exception):
    pass


Sender = Callable[[str, str, Optional[dict]], dict]


def http_sender(key: str, api: str = API) -> Sender:
    def send(method: str, path: str, body: Optional[dict]) -> dict:
        data = None if body is None else json.dumps(body).encode("utf-8")
        req = urllib.request.Request(api + path, data=data, method=method)
        req.add_header("authorization", f"Bearer {key}")
        req.add_header("accept", "application/json")
        req.add_header("user-agent", "walnut-provision/1")
        if data is not None:
            req.add_header("content-type", "application/json")
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                raw = r.read()
                return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "replace")[:300]
            raise VultrError(f"{method} {path}: HTTP {e.code} {detail}") from None
    return send


def dry_sender(log: Callable[[str], None]) -> Sender:
    """Prints each request instead of sending it, and returns plausible ids so the plan reads end to end."""
    counter = {"n": 0}

    def send(method: str, path: str, body: Optional[dict]) -> dict:
        shown = dict(body or {})
        if "user_data" in shown:
            shown["user_data"] = f"<base64 of cloud-init.yaml, {len(shown['user_data'])} chars>"
        log(f"DRY-RUN  {method} {API}{path}" + (f"  {json.dumps(shown)}" if body is not None else ""))
        counter["n"] += 1
        fake = f"dry-run-{counter['n']}"
        if method == "GET" and path.startswith("/os"):
            return {"os": [{"id": 0, "name": "Ubuntu 24.04 LTS x64"}], "meta": {"links": {"next": ""}}}
        if method == "GET" and path.startswith("/instances?"):
            return {"instances": [], "meta": {"links": {"next": ""}}}
        if method == "GET" and path.startswith("/ssh-keys"):
            return {"ssh_keys": [], "meta": {"links": {"next": ""}}}
        if path == "/firewalls":
            return {"firewall_group": {"id": fake}}
        if path.endswith("/rules"):
            return {"firewall_rule": {"id": counter["n"]}}
        if path == "/ssh-keys":
            return {"ssh_key": {"id": fake}}
        if path == "/instances":
            return {"instance": {"id": fake, "main_ip": "0.0.0.0", "status": "pending"}}
        if path.startswith("/instances/"):
            return {"instance": {"id": path.rsplit("/", 1)[-1], "main_ip": "203.0.113.10", "status": "active",
                                 "power_status": "running", "server_status": "ok"}}
        return {}
    return send


def my_ip() -> str:
    for url in ("https://api.ipify.org", "https://ifconfig.me/ip"):
        try:
            with urllib.request.urlopen(url, timeout=8) as r:
                ip = r.read().decode().strip()
                if ip.count(".") == 3:
                    return ip
        except (urllib.error.URLError, OSError):
            continue
    raise VultrError("could not find your public IP for the SSH rule; pass --ssh-from <ip>")


def user_data(repo_url: str, branch: str = "main") -> str:
    text = CLOUD_INIT.read_text(encoding="utf-8")
    if "REPO_URL" not in text:
        raise VultrError("cloud-init.yaml has no REPO_URL placeholder")
    text = text.replace("--branch main REPO_URL", f"--branch {branch} {repo_url}")
    return base64.b64encode(text.encode("utf-8")).decode("ascii")


def find_os_id(send: Sender, name: str) -> int:
    for o in send("GET", "/os?per_page=500", None).get("os", []):
        if o.get("name") == name:
            return int(o["id"])
    raise VultrError(f"no OS image named {name!r} (GET /v2/os)")


def plan(send: Sender, *, repo_url: str, ssh_pub: str, ssh_from: str, region: str, vm_plan: str,
         os_name: str, label: str, branch: str, log: Callable[[str], None],
         wait_s: float = 600, sleep: Callable[[float], None] = time.sleep) -> dict[str, Any]:
    out: dict[str, Any] = {}
    running = [i for i in send("GET", f"/instances?label={label}&per_page=500", None).get("instances", [])
               if i.get("label") == label]
    if running:
        raise VultrError(f"an instance labelled {label!r} already exists ({running[0].get('id')}, "
                         f"{running[0].get('main_ip')}): not creating a second billed VM. Destroy it first, "
                         f"or pass another --label")
    log("1/4 firewall group")
    fw = send("POST", "/firewalls", {"description": f"{label}-web"})["firewall_group"]["id"]
    rules = [("tcp", "22", ssh_from, 32, "ssh from the operator only"),
             ("tcp", "80", "0.0.0.0", 0, "http: Let's Encrypt challenge and redirect"),
             ("tcp", "443", "0.0.0.0", 0, "https")]
    for proto, port, subnet, size, notes in rules:
        send("POST", f"/firewalls/{fw}/rules", {"ip_type": "v4", "protocol": proto, "subnet": subnet,
                                                 "subnet_size": size, "port": port, "notes": notes})
    out["firewall_group_id"] = fw

    log("2/4 ssh key")
    key_name = f"{label}-key"
    existing = [k for k in send("GET", "/ssh-keys?per_page=500", None).get("ssh_keys", [])
                if k.get("name") == key_name]
    key_id = existing[0]["id"] if existing else send("POST", "/ssh-keys", {"name": key_name, "ssh_key": ssh_pub})["ssh_key"]["id"]
    out["sshkey_id"] = key_id

    log("3/4 cloud compute VM")
    os_id = find_os_id(send, os_name)
    inst = send("POST", "/instances", {
        "region": region, "plan": vm_plan, "os_id": os_id, "label": label, "hostname": label,
        "sshkey_id": [key_id], "firewall_group_id": fw, "backups": "disabled", "enable_ipv6": False,
        "tags": ["walnut"], "user_data": user_data(repo_url, branch)})["instance"]
    out["instance_id"] = inst["id"]

    log("4/4 waiting for the public IPv4")
    deadline = time.monotonic() + wait_s
    ip = inst.get("main_ip") or "0.0.0.0"
    while ip in ("", "0.0.0.0"):
        if time.monotonic() > deadline:
            raise VultrError("timed out waiting for the VM's IP; check the Vultr console")
        sleep(10)
        ip = send("GET", f"/instances/{inst['id']}", None)["instance"].get("main_ip") or "0.0.0.0"
    out["ip"] = ip
    out["url"] = f"https://{ip.replace('.', '-')}.sslip.io"
    return out


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Provision Walnut on Vultr (firewall group + Cloud Compute VM).")
    ap.add_argument("--repo-url", help="PUBLIC git URL of this repository (cloned by cloud-init)")
    ap.add_argument("--branch", default="main")
    ap.add_argument("--ssh-key", help="path to your SSH PUBLIC key (.pub)")
    ap.add_argument("--ssh-from", help="IPv4 allowed to SSH (default: your current public IP)")
    ap.add_argument("--region", default="sgp", help="Vultr region id (default sgp, Singapore)")
    ap.add_argument("--plan", default="vc2-2c-4gb", help="Vultr plan id (default vc2-2c-4gb: 2 vCPU / 4 GB)")
    ap.add_argument("--os-name", default="Ubuntu 24.04 LTS x64")
    ap.add_argument("--label", default="walnut-demo")
    ap.add_argument("--apply", action="store_true", help="really call the Vultr API (default: dry run)")
    ap.add_argument("--destroy", metavar="INSTANCE_ID", help="delete this instance (stops billing) and exit")
    a = ap.parse_args(argv)
    log = lambda s: print(s, flush=True)                              # noqa: E731

    key = os.environ.get("VULTR_API_KEY", "").strip()
    if a.apply and not key:
        print("VULTR_API_KEY is not set (Vultr console -> Account -> API)", file=sys.stderr)
        return 2
    send = http_sender(key) if a.apply else dry_sender(log)
    if a.destroy:
        send("DELETE", f"/instances/{a.destroy}", None)
        log(f"deleted instance {a.destroy}" if a.apply else "(dry run)")
        return 0
    if not a.repo_url or not a.ssh_key:
        ap.error("--repo-url and --ssh-key are required")
    ssh_pub = Path(os.path.expanduser(a.ssh_key)).read_text(encoding="utf-8").strip() if a.apply else \
        (Path(os.path.expanduser(a.ssh_key)).read_text(encoding="utf-8").strip()
         if Path(os.path.expanduser(a.ssh_key)).exists() else "ssh-ed25519 AAAA...dry-run")
    if a.apply and not ssh_pub.startswith(("ssh-", "ecdsa-")):
        print("--ssh-key must be a PUBLIC key file (.pub)", file=sys.stderr)
        return 2
    ssh_from = a.ssh_from or (my_ip() if a.apply else "198.51.100.7")
    if not a.apply:
        log("Dry run: nothing is sent to Vultr. Add --apply (with VULTR_API_KEY set) to create these.")
    try:
        res = plan(send, repo_url=a.repo_url, ssh_pub=ssh_pub, ssh_from=ssh_from, region=a.region,
                   vm_plan=a.plan, os_name=a.os_name, label=a.label, branch=a.branch, log=log,
                   sleep=time.sleep if a.apply else (lambda s: None))
    except VultrError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1
    log(json.dumps(res, indent=2))
    key_arg = re.sub(r"\.pub$", "", a.ssh_key)
    if " " in key_arg:                          # a Windows user name with a space, expanded by the shell
        key_arg = f'"{key_arg}"'
    ssh = f"ssh -i {key_arg} root@{res['ip']}"
    log(f"\nFirst boot deploys the stack (about 15-20 min). Then:\n"
        f"  {ssh} 'tail -F /var/log/walnut-deploy.log'    (ends with the URL and the passcode)\n"
        f"  open {res['url']}\n"
        f"  optional model: {ssh} then 'bash /opt/walnut/repo/deploy/docker/deploy.sh configure-model vultr'\n"
        f"  SSH refused later? Your IP changed: edit the firewall group's port 22 rule in the Vultr console.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
