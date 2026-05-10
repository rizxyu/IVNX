import os
import json
import uuid
import subprocess
import time
import sys
import random

# =========================================
# CONFIG
# =========================================
CONFIG_PATH = "/usr/local/etc/xray/config.json"

DOMAIN = "example.com"

if os.path.exists(".env"):
    with open(".env", "r") as f:
        for line in f:
            if "=" in line:
                k, v = line.strip().split("=", 1)

                if k == "DOMAIN":
                    DOMAIN = v

# =========================================
# COLOR
# =========================================
GREEN = '\033[0;32m'
RED = '\033[0;31m'
YELLOW = '\033[1;33m'
BLUE = '\033[0;34m'
NC = '\033[0m'

# =========================================
# LOGGER
# =========================================
def success(msg):
    print(f"{GREEN}[SUCCESS]{NC} {msg}")

def error(msg):
    print(f"{RED}[ERROR]{NC} {msg}")

def info(msg):
    print(f"{YELLOW}[INFO]{NC} {msg}")

def process(msg):
    print(f"{BLUE}[PROCESS]{NC} {msg}")

# =========================================
# RUN CMD
# =========================================
def run(cmd, show=True):
    try:
        subprocess.run(
            cmd,
            shell=True,
            check=True,
            stdout=None if show else subprocess.DEVNULL,
            stderr=None if show else subprocess.DEVNULL
        )
        return True
    except:
        return False

# =========================================
# FORCE FREE PORT
# =========================================
def free_port(port):
    process(f"Freeing port {port}")

    try:
        pids = subprocess.getoutput(
            f"lsof -t -i:{port}"
        ).strip()

        if pids:
            for pid in pids.split("\n"):
                info(f"Killing PID {pid}")
                run(f"kill -9 {pid}")

        run(f"fuser -k {port}/tcp")

        services = [
            "nginx",
            "apache2",
            "httpd",
            "caddy",
            "haproxy",
            "xray",
            "v2ray"
        ]

        for svc in services:
            run(f"systemctl stop {svc}", False)

        time.sleep(2)

        check = subprocess.getoutput(
            f"ss -tulnp | grep :{port}"
        )

        if check.strip():
            error(f"Port {port} still used")
            print(check)
            return False

        success(f"Port {port} free")
        return True

    except Exception as e:
        error(str(e))
        return False

# =========================================
# INSTALL DEPENDENCY
# =========================================
def install_dependencies():
    process("Installing dependencies")

    pkgs = [
        "curl",
        "wget",
        "unzip",
        "tar",
        "certbot",
        "socat",
        "jq",
        "lsof",
        "iptables",
        "iproute2"
    ]

    run("apt-get update")
    run(f"apt-get install -y {' '.join(pkgs)}")

    success("Dependencies installed")

# =========================================
# INSTALL XRAY
# =========================================
def install_xray():
    process("Installing Xray")

    free_port(80)
    free_port(443)

    run("mkdir -p /usr/local/etc/xray")
    run("mkdir -p /var/log/xray")

    run("rm -rf /tmp/xray")
    run("rm -rf /tmp/xray.zip")

    url = "https://github.com/XTLS/Xray-core/releases/latest/download/Xray-linux-64.zip"

    if not run(f"curl -L {url} -o /tmp/xray.zip"):
        error("Download failed")
        return

    if not run("unzip -o /tmp/xray.zip -d /tmp/xray"):
        error("Extract failed")
        return

    run("rm -f /usr/local/bin/xray")
    run("mv /tmp/xray/xray /usr/local/bin/xray")
    run("chmod +x /usr/local/bin/xray")

    process("Generating SSL")

    run("rm -rf /etc/letsencrypt")

    cert = (
        f"certbot certonly "
        f"--standalone "
        f"--non-interactive "
        f"--agree-tos "
        f"--register-unsafely-without-email "
        f"-d {DOMAIN}"
    )

    if not run(cert):
        error("SSL failed")
        return

    client_uuid = str(uuid.uuid4())

    config = {
        "log": {
            "access": "/var/log/xray/access.log",
            "error": "/var/log/xray/error.log",
            "loglevel": "warning"
        },
        "inbounds": [
            {
                "port": 443,
                "protocol": "vless",
                "settings": {
                    "clients": [
                        {
                            "id": client_uuid,
                            "flow": "xtls-rprx-vision"
                        }
                    ],
                    "decryption": "none"
                },
                "streamSettings": {
                    "network": "tcp",
                    "security": "tls",
                    "tlsSettings": {
                        "certificates": [
                            {
                                "certificateFile":
                                f"/etc/letsencrypt/live/{DOMAIN}/fullchain.pem",
                                "keyFile":
                                f"/etc/letsencrypt/live/{DOMAIN}/privkey.pem"
                            }
                        ]
                    }
                }
            }
        ],
        "outbounds": [
            {
                "protocol": "freedom",
                "tag": "direct"
            }
        ]
    }

    with open(CONFIG_PATH, "w") as f:
        json.dump(config, f, indent=4)

    service = f"""
[Unit]
Description=Xray
After=network.target

[Service]
ExecStart=/usr/local/bin/xray run -config {CONFIG_PATH}
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
"""

    with open("/etc/systemd/system/xray.service", "w") as f:
        f.write(service)

    run("systemctl daemon-reload")
    run("systemctl enable xray")

    if not run("systemctl restart xray"):
        error("Failed start Xray")
        return

    time.sleep(5)

    status = subprocess.getoutput(
        "systemctl is-active xray"
    ).strip()

    if status != "active":
        error("Xray failed")

        logs = subprocess.getoutput(
            "journalctl -u xray --no-pager -n 30"
        )

        print(logs)
        return

    success("Xray installed")

    vless = (
        f"vless://{client_uuid}@{DOMAIN}:443"
        f"?security=tls"
        f"&encryption=none"
        f"&type=tcp"
        f"&flow=xtls-rprx-vision"
        f"#XRAY"
    )

    print("\n")
    print("=" * 60)
    print(vless)
    print("=" * 60)

# =========================================
# LOAD PROXY FILE
# =========================================
def load_proxies():
    proxies = []

    if not os.path.exists("proxy.txt"):
        return proxies

    with open("proxy.txt", "r") as f:
        for line in f:
            line = line.strip()

            if not line:
                continue

            parts = line.split(":")

            if len(parts) != 4:
                continue

            proxies.append({
                "ip": parts[0],
                "port": parts[1],
                "user": parts[2],
                "password": parts[3]
            })

    return proxies

# =========================================
# APPLY ALL PROXY
# =========================================
def apply_proxy():
    process("Applying proxies")

    proxies = load_proxies()

    if not proxies:
        error("proxy.txt empty")
        return

    if not os.path.exists(CONFIG_PATH):
        error("Xray config not found")
        return

    with open(CONFIG_PATH, "r") as f:
        config = json.load(f)

    outbounds = []

    for i, proxy in enumerate(proxies):
        outbound = {
            "tag": f"proxy{i+1}",
            "protocol": "socks",
            "settings": {
                "servers": [
                    {
                        "address": proxy["ip"],
                        "port": int(proxy["port"]),
                        "users": [
                            {
                                "user": proxy["user"],
                                "pass": proxy["password"]
                            }
                        ]
                    }
                ]
            }
        }

        outbounds.append(outbound)

    outbounds.append({
        "protocol": "freedom",
        "tag": "direct"
    })

    config["outbounds"] = outbounds

    with open(CONFIG_PATH, "w") as f:
        json.dump(config, f, indent=4)

    run("systemctl restart xray")

    success(f"{len(proxies)} proxies loaded")

# =========================================
# RANDOM ROTATE PROXY
# =========================================
def rotate_proxy():
    process("Rotating proxy")

    proxies = load_proxies()

    if not proxies:
        error("proxy.txt empty")
        return

    proxy = random.choice(proxies)

    with open(CONFIG_PATH, "r") as f:
        config = json.load(f)

    config["outbounds"] = [
        {
            "tag": "proxy",
            "protocol": "socks",
            "settings": {
                "servers": [
                    {
                        "address": proxy["ip"],
                        "port": int(proxy["port"]),
                        "users": [
                            {
                                "user": proxy["user"],
                                "pass": proxy["password"]
                            }
                        ]
                    }
                ]
            }
        }
    ]

    with open(CONFIG_PATH, "w") as f:
        json.dump(config, f, indent=4)

    run("systemctl restart xray")

    success(
        f"Using proxy {proxy['ip']}:{proxy['port']}"
    )

# =========================================
# REMOVE PROXY
# =========================================
def remove_proxy():
    process("Removing proxy config")

    if not os.path.exists(CONFIG_PATH):
        error("Xray config not found")
        return

    with open(CONFIG_PATH, "r") as f:
        config = json.load(f)

    config["outbounds"] = [
        {
            "protocol": "freedom",
            "tag": "direct"
        }
    ]

    with open(CONFIG_PATH, "w") as f:
        json.dump(config, f, indent=4)

    run("systemctl restart xray")

    success("Proxy removed")
    success("Using direct connection")

# =========================================
# BANDWIDTH LIMIT
# =========================================
def set_bandwidth():
    print("\nExample:")
    print("1mbit")
    print("5mbit")
    print("10mbit")
    print("50mbit")

    limit = input("\nInput bandwidth: ").strip()

    if not limit:
        error("Invalid limit")
        return

    process("Setting bandwidth")

    run("tc qdisc del dev eth0 root", False)

    cmd = (
        f"tc qdisc add dev eth0 root "
        f"tbf rate {limit} burst 32kbit latency 400ms"
    )

    if run(cmd):
        success(f"Bandwidth limited to {limit}")
    else:
        error("Failed set bandwidth")

# =========================================
# REMOVE BANDWIDTH LIMIT
# =========================================
def remove_bandwidth():
    process("Removing bandwidth limit")

    if run("tc qdisc del dev eth0 root", False):
        success("Bandwidth unlimited")
    else:
        error("Failed remove limit")

# =========================================
# STATUS
# =========================================
def status():
    print("\nXRAY STATUS")
    print(
        subprocess.getoutput(
            "systemctl is-active xray"
        )
    )

    print("\nPORT 443")
    print(
        subprocess.getoutput(
            "ss -tulnp | grep :443"
        )
    )

    print("\nBANDWIDTH")
    print(
        subprocess.getoutput(
            "tc qdisc show dev eth0"
        )
    )

# =========================================
# RESTART
# =========================================
def restart():
    process("Restarting Xray")

    run("systemctl restart xray")

    success("Restarted")

# =========================================
# UNINSTALL
# =========================================
def uninstall():
    process("Removing Xray")

    run("systemctl stop xray", False)
    run("systemctl disable xray", False)

    run("rm -rf /usr/local/bin/xray")
    run("rm -rf /usr/local/etc/xray")
    run("rm -rf /etc/systemd/system/xray.service")
    run("rm -rf /var/log/xray")
    run("rm -rf /etc/letsencrypt")

    run("systemctl daemon-reload")

    success("Removed")

# =========================================
# MENU
# =========================================
def menu():
    while True:
        print(f"""
{BLUE}
=================================
 XRAY PROXY MANAGER
=================================
{NC}

1. Install Dependencies
2. Install Xray
3. Apply Proxy.txt
4. Rotate Random Proxy
5. Remove Proxy
6. Set Bandwidth
7. Remove Bandwidth Limit
8. Check Status
9. Restart Xray
10. Free Port 443
11. Uninstall
0. Exit
""")

        choice = input(f"{YELLOW}Select:{NC} ")

        if choice == "1":
            install_dependencies()

        elif choice == "2":
            install_xray()

        elif choice == "3":
            apply_proxy()

        elif choice == "4":
            rotate_proxy()

        elif choice == "5":
            remove_proxy()

        elif choice == "6":
            set_bandwidth()

        elif choice == "7":
            remove_bandwidth()

        elif choice == "8":
            status()

        elif choice == "9":
            restart()

        elif choice == "10":
            free_port(443)

        elif choice == "11":
            uninstall()

        elif choice == "0":
            break

        else:
            error("Invalid menu")

# =========================================
# ROOT CHECK
# =========================================
if __name__ == "__main__":
    if os.geteuid() != 0:
        print("Run as root")
        sys.exit(1)

    menu()
