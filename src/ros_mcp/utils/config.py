from pathlib import Path

import yaml

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
_ROBOTS_DIR = _PROJECT_ROOT / "robots"


def load_robot_config(robot_name: str, specs_dir: str) -> dict:
    """Load a robot configuration YAML file by name.

    Raises FileNotFoundError if the file does not exist.
    """
    file_path = Path(specs_dir) / f"{robot_name}.yaml"
    if not file_path.exists():
        raise FileNotFoundError(f"Robot config file not found: {file_path}")

    with file_path.open() as f:
        return yaml.safe_load(f) or {}


def get_verified_robot_spec_util(name: str) -> dict:
    """Load and validate a robot spec, returning ``{name: {type, prompts}}``."""
    name = name.replace(" ", "_")
    config = load_robot_config(name, str(_ROBOTS_DIR))

    if not config:
        raise ValueError(f"No configuration found for robot '{name}'")

    for field in ("type", "prompts"):
        if field not in config or config[field] in (None, ""):
            raise ValueError(f"Robot '{name}' is missing required field: {field}")

    return {name: {"type": config["type"], "prompts": config["prompts"]}}


def get_verified_robots_list_util() -> dict:
    """Return available robot spec names from the robots/ directory."""
    if not _ROBOTS_DIR.exists():
        return {"error": f"Robot specifications directory not found: {_ROBOTS_DIR}"}

    yaml_files = list(_ROBOTS_DIR.glob("*.yaml"))
    if not yaml_files:
        return {"error": "No robot specification files found"}

    robot_names = sorted(f.stem for f in yaml_files if not f.stem.startswith("_"))
    return {"robots": robot_names, "count": len(robot_names)}
