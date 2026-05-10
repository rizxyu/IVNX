import os
import subprocess
import json
import uuid
import time
import sys

def load_env():
    env_vars = {}
    if os.path.exists(".env"):
        with open(".env", "r") as f:
            for line in f:
                if "=" in line and not line.startswith("#"):
                    k, v = line.strip().split("=", 1)
                    env_vars[k] = v.strip()
    return env_vars

def get_proxy_list():
    if os.path.exists("proxy.txt"):
        with open("proxy.txt", "r") as f:
            return [line.strip() for line in f if line.strip()]
    return []

env = load_env()
SUBDOMAIN = env.get("SUBDOMAIN", "v2less-vip.academygpt.biz.id")

def jalankan_perintah_dengan_retry_proxy(cmd):
    proxies = get_proxy_list()
    
    # Jika tidak ada proxy, jalankan normal
    if not proxies:
        return subprocess.run(cmd, shell=True, check=False).returncode == 0

    # Jika ada, coba satu-satu sampai berhasil
    for prx in proxies:
        print(f"[*] Mencoba dengan proxy: {prx}")
        env_cmd = os.environ.copy()
        env_cmd["http_proxy"] = prx
        env_cmd["https_proxy"] = prx
        try:
            res = subprocess.run(cmd, shell=True, check=True, env=env_cmd)
            return True
        except subprocess.CalledProcessError:
            print(f"[!] Proxy {prx} gagal, mencoba proxy berikutnya...")
            continue
    
    return False

def setup_ssl():
    print(f"[*] Memproses SSL untuk {SUBDOMAIN}...")
    subprocess.run("fuser -k 80/tcp || true", shell=True)
    # SSL biasanya butuh koneksi langsung atau proxy yang sangat stabil
    cmd_cert = f"certbot certonly --standalone -d {SUBDOMAIN} --non-interactive --agree-tos --register-unsafely-without-email"
    return jalankan_perintah_dengan_retry_proxy(cmd_cert)

def instalasi_xray():
    REPO_URL = "https://github.com/rizxyu/Xray-core"
    print(f"[*] Build Xray-core dari {REPO_URL}...")
    
    if not os.path.exists("/usr/local/src/xray-core"):
        jalankan_perintah_dengan_retry_proxy(f"git clone {REPO_URL} /usr/local/src/xray-core")
    else:
        jalankan_perintah_dengan_retry_proxy("cd /usr/local/src/xray-core && git pull")
    
    # Build dengan optimasi
    jalankan_perintah_dengan_retry_proxy("cd /usr/local/src/xray-core && go build -o xray -trimpath -ldflags '-s -w' ./main")
    subprocess.run("cp /usr/local/src/xray-core/xray /usr/local/bin/xray && chmod +x /usr/local/bin/xray", shell=True)

def konfigurasi_vless():
    client_uuid = str(uuid.uuid4())
    config = {
        "log": {"loglevel": "warning", "access": "/var/log/xray/access.log"},
        "inbounds": [{
            "port": 443,
            "protocol": "vless",
            "settings": {
                "clients": [{"id": client_uuid, "flow": "xtls-rprx-vision"}],
                "decryption": "none"
            },
            "streamSettings": {
                "network": "tcp",
                "security": "tls",
                "tlsSettings": {
                    "serverName": SUBDOMAIN,
                    "certificates": [{
                        "certificateFile": f"/etc/letsencrypt/live/{SUBDOMAIN}/fullchain.pem",
                        "keyFile": f"/etc/letsencrypt/live/{SUBDOMAIN}/privkey.pem"
                    }]
                }
            }
        }],
        "outbounds": [{"protocol": "freedom"}]
    }
    
    os.makedirs("/usr/local/etc/xray", exist_ok=True)
    with open("/usr/local/etc/xray/config.json", "w") as f:
        json.dump(config, f, indent=4)
    return client_uuid

def setup_systemd():
    service_content = f"""[Unit]
Description=Xray V2LESS-VIP Service
After=network.target nss-lookup.target

[Service]
User=root
ExecStart=/usr/local/bin/xray run -config /usr/local/etc/xray/config.json
Restart=always
RestartSec=5
LimitNOFILE=1000000

[Install]
WantedBy=multi-user.target
"""
    with open("/etc/systemd/system/xray.service", "w") as f:
        f.write(service_content)
    
    subprocess.run("systemctl daemon-reload && systemctl enable xray && systemctl restart xray", shell=True)

if __name__ == "__main__":
    if os.geteuid() != 0:
        print("[!] Harus dijalankan sebagai root!")
        sys.exit(1)

    print(f"--- SETUP XRAY (MULTI-PROXY SUPPORT) UNTUK {SUBDOMAIN} ---")
    
    jalankan_perintah_dengan_retry_proxy("apt-get update && apt-get install -y git golang certbot")
    
    if setup_ssl():
        instalasi_xray()
        u_id = konfigurasi_vless()
        setup_systemd()
        print(f"\n[ BERHASIL ]")
        print(f"VLESS Link: vless://{u_id}@{SUBDOMAIN}:443?encryption=none&security=tls&sni={SUBDOMAIN}&fp=chrome&type=tcp&flow=xtls-rprx-vision#V2LESS-VIP")
    else:
        print("[!] Gagal mendapatkan SSL. Periksa list proxy di proxy.txt atau DNS Record.")
