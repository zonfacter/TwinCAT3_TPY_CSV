from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from .exceptions import ConfigError


@dataclass
class AppConfig:
    output_dir: str = ""
    only_file: str = ""
    skip_file: str = ""
    recurse: bool = True
    recurse_array: bool = True
    input_files: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AppConfig":
        return cls(
            output_dir=str(data.get("output_dir", "")),
            only_file=str(data.get("only_file", "")),
            skip_file=str(data.get("skip_file", "")),
            recurse=bool(data.get("recurse", True)),
            recurse_array=bool(data.get("recurse_array", True)),
            input_files=[str(p) for p in (data.get("input_files", []) or [])],
        )


def get_app_dir() -> Path:
    """
    Returns a per-user config directory.

    Windows: %APPDATA%\\TPY_CSV_GUI
    Fallback: ~/.tpy_csv_gui
    """
    appdata = os.environ.get("APPDATA")
    if appdata:
        return Path(appdata) / "TPY_CSV_GUI"
    return Path.home() / ".tpy_csv_gui"


def get_config_path() -> Path:
    return get_app_dir() / "config.json"


def load_config() -> AppConfig:
    path = get_config_path()
    if not path.exists():
        return AppConfig()

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ConfigError("Config JSON root is not an object.")
        return AppConfig.from_dict(data)
    except (OSError, json.JSONDecodeError) as exc:
        raise ConfigError(f"Failed to load config: {exc}") from exc


def save_config(cfg: AppConfig) -> None:
    app_dir = get_app_dir()
    path = get_config_path()
    try:
        app_dir.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(cfg.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")
    except OSError as exc:
        raise ConfigError(f"Failed to save config: {exc}") from exc


def normalize_existing_paths(paths: List[str]) -> List[str]:
    out: List[str] = []
    for p in paths:
        try:
            if Path(p).exists():
                out.append(p)
        except OSError:
            continue
    return out
