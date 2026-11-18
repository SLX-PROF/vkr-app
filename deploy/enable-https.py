"""Однократная штатная настройка Caddy; запуск администратором VPS через sudo."""
import os
import shutil
import socket
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path

HOST = "vkr.141.133.175.204.nip.io"
IP = "141.133.175.204"
CONFIG = Path("/etc/caddy/Caddyfile")


def main():
    if os.geteuid() != 0:
        raise SystemExit("Запустите этот файл через sudo python3.")
    if IP not in {r[4][0] for r in socket.getaddrinfo(HOST, 443)}:
        raise SystemExit("Бесплатное имя пока не указывает на этот VPS; конфигурация не изменена.")
    original = CONFIG.read_bytes()
    if HOST.encode() in original:
        raise SystemExit("Адрес уже встречается в Caddyfile; сначала проверьте действующую настройку.")
    block = f"\n\n{HOST} {{\n    bind {IP}\n    reverse_proxy 127.0.0.1:8765\n}}\n"
    candidate = original + block.encode()
    with tempfile.NamedTemporaryFile(dir=CONFIG.parent, prefix="vkr-caddy-", delete=False) as f:
        f.write(candidate)
        temporary = Path(f.name)
    try:
        subprocess.run(["caddy", "validate", "--config", str(temporary), "--adapter", "caddyfile"], check=True)
        suffix = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        backup = CONFIG.with_name(f"Caddyfile.before-vkr-{suffix}")
        shutil.copy2(CONFIG, backup)
        temporary.chmod(CONFIG.stat().st_mode & 0o777)
        os.replace(temporary, CONFIG)
        result = subprocess.run(["systemctl", "reload", "caddy"])
        if result.returncode:
            shutil.copy2(backup, CONFIG)
            subprocess.run(["systemctl", "reload", "caddy"], check=True)
            raise SystemExit("Не удалось применить настройку; исходный файл восстановлен.")
        print(f"Адрес подключён: https://{HOST}/. Резервная копия: {backup}")
    finally:
        temporary.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
