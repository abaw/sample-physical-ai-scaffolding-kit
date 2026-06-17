"""Load ~/.physai/config.yaml and merge with CLI flags."""

from pathlib import Path

import yaml

from .schema import validate

CONFIG_PATH = Path.home() / ".physai" / "config.yaml"

DEFAULTS = {
    "host": None,
    "ssh_config": None,
    "model_config_roots": [],
}


def load(
    host_override: str | None = None,
    ssh_config_override: str | None = None,
) -> dict:
    cfg = dict(DEFAULTS)
    if CONFIG_PATH.exists():
        with open(CONFIG_PATH) as f:
            file_cfg = yaml.safe_load(f) or {}
        validate(file_cfg, "cli-config", str(CONFIG_PATH))
        cfg.update(file_cfg)
    if host_override:
        cfg["host"] = host_override
    if ssh_config_override:
        cfg["ssh_config"] = ssh_config_override
    if cfg["ssh_config"]:
        cfg["ssh_config"] = str(Path(cfg["ssh_config"]).expanduser())
    if not cfg["host"]:
        raise SystemExit(
            "No host configured. Set 'host' in ~/.physai/config.yaml or pass --host."
        )
    return cfg
