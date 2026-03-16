import platform
import re
import socket
import subprocess

# Matches IPv4, IPv6 (including bracketed), or hostname (alphanumeric + hyphens + dots)
_VALID_HOST_RE = re.compile(
    r"^("
    r"\d{1,3}(\.\d{1,3}){3}"           # IPv4
    r"|[\da-fA-F:]{2,39}"              # IPv6
    r"|\[[\da-fA-F:]{2,39}\]"          # bracketed IPv6
    r"|[a-zA-Z0-9]([a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?(\.[a-zA-Z0-9]([a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?)*"  # hostname
    r")$"
)


_OVERALL_STATUS = {
    (True, True): "accessible",
    (True, False): "ip_reachable_port_closed",
    (False, True): "ip_unreachable_port_open",
    (False, False): "unreachable",
}


def ping_ip_and_port(
    ip: str, port: int, ping_timeout: float = 2.0, port_timeout: float = 2.0
) -> dict:
    """Ping an IP address and check whether a specific port is open."""
    if not _VALID_HOST_RE.match(ip):
        return {
            "ip": ip,
            "port": port,
            "error": "Invalid IP address or hostname format",
            "overall_status": "invalid_input",
        }

    result = {
        "ip": ip,
        "port": port,
        "ping": {"success": False, "error": None, "response_time_ms": None},
        "port_check": {"open": False, "error": None},
        "overall_status": "unknown",
    }

    _check_ping(result, ip, ping_timeout)
    _check_port(result, ip, port, port_timeout)

    result["overall_status"] = _OVERALL_STATUS[
        result["ping"]["success"], result["port_check"]["open"]
    ]
    return result


def _extract_ping_time(stdout: str) -> float | None:
    """Extract response time in ms from ping output (format: 'time=X.XX ms')."""
    for line in stdout.split("\n"):
        if "time=" not in line:
            continue
        try:
            return float(line.split("time=")[1].split()[0])
        except (ValueError, IndexError):
            return None
    return None


def _check_ping(result: dict, ip: str, timeout: float) -> None:
    """Run a single ICMP ping and populate result['ping']."""
    try:
        if platform.system().lower() == "windows":
            cmd = ["ping", "-n", "1", "-w", str(int(timeout * 1000)), ip]
        else:
            cmd = ["ping", "-c", "1", "-W", str(int(timeout)), ip]

        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout + 1.0)

        if proc.returncode == 0:
            result["ping"]["success"] = True
            result["ping"]["response_time_ms"] = _extract_ping_time(proc.stdout)
        else:
            result["ping"]["error"] = f"Ping failed with return code {proc.returncode}"

    except subprocess.TimeoutExpired:
        result["ping"]["error"] = f"Ping timeout after {timeout} seconds"
    except FileNotFoundError:
        result["ping"]["error"] = "Ping command not found on this system"
    except Exception as e:
        result["ping"]["error"] = f"Ping error: {e}"


def _check_port(result: dict, ip: str, port: int, timeout: float) -> None:
    """Attempt a TCP connection and populate result['port_check']."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(timeout)
            port_result = sock.connect_ex((ip, port))

        if port_result == 0:
            result["port_check"]["open"] = True
        else:
            result["port_check"]["error"] = (
                f"Port {port} is closed or unreachable (error code: {port_result})"
            )

    except socket.timeout:
        result["port_check"]["error"] = (
            f"Port {port} connection timeout after {timeout} seconds"
        )
    except socket.gaierror as e:
        result["port_check"]["error"] = f"DNS resolution error: {e}"
    except Exception as e:
        result["port_check"]["error"] = f"Port check error: {e}"
