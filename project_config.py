import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
ENV_PATH = PROJECT_ROOT / ".env"


def _strip_quotes(value):
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        quoted = value[1:-1]
        result = []
        escaped = False
        for char in quoted:
            if escaped:
                result.append({"n": "\n", "r": "\r", "t": "\t"}.get(char, char))
                escaped = False
            elif char == "\\":
                escaped = True
            else:
                result.append(char)
        if escaped:
            result.append("\\")
        return "".join(result)
    return value


def parse_env_file(path=ENV_PATH):
    values = {}
    if not path.exists():
        return values

    for raw_line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if key:
            values[key] = _strip_quotes(value)
    return values


def load_env_file(path=ENV_PATH, override=False):
    """Load project .env values without overriding real environment variables."""
    for key, value in parse_env_file(path).items():
        if override or key not in os.environ:
            os.environ[key] = value


def env_str(name, default=""):
    load_env_file()
    value = os.getenv(name)
    if not value:
        return default
    return value


def env_int(name, default):
    value = env_str(name, str(default)).strip()
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def env_path(name, default):
    return Path(env_str(name, str(default)))


def env_path_str(name, default):
    return str(env_path(name, default))
