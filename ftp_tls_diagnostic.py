"""Safe FTPS connection diagnostic using credentials supplied through .env."""
import ssl
from ftplib import FTP_TLS

from project_config import env_int, env_str, load_env_file


def main() -> int:
    load_env_file()
    host = env_str("FTP_HOST")
    username = env_str("FTP_USERNAME")
    password = env_str("FTP_PASSWORD")
    port = env_int("FTP_PORT", 21)
    ignore_cert = env_str("FTP_IGNORE_CERT", "False").lower() in {"true", "1", "yes", "on"}
    if not all((host, username, password)):
        raise SystemExit("Set FTP_HOST, FTP_USERNAME, and FTP_PASSWORD in .env before testing FTPS.")

    context = ssl.create_default_context()
    if ignore_cert:
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
        print("Warning: certificate validation is disabled for this diagnostic.")

    client = FTP_TLS(context=context)
    try:
        client.connect(host, port, timeout=env_int("FTP_TIMEOUT_SECONDS", 30))
        client.auth()
        client.login(username, password)
        client.prot_p()
        print(f"FTPS connection succeeded: {client.getwelcome()}")
        return 0
    finally:
        try:
            client.quit()
        except Exception:
            client.close()


if __name__ == "__main__":
    raise SystemExit(main())
