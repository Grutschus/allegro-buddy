"""Layered configuration: shipped cluster preset < site file < user file.

Command-line flags sit on top (for `ab dev start` via click's ``default_map``), and
whatever no layer sets is detected from Slurm or falls back to a built-in default
in the code that reads it.
"""

from __future__ import annotations

import configparser
import functools
import os
import re
import socket
import subprocess
from dataclasses import dataclass, field
from functools import cached_property
from importlib import resources
from pathlib import Path

# `ab dev start` options a user may preset in [dev]; maps config key -> click parameter.
DEV_START_KEYS = {
    'partition': 'partition',
    'time': 'time_limit',
    'gpu': 'gpu',
    'gpu_type': 'gpu_type',
    'cpus': 'cpus',
    'mem': 'mem',
    'account': 'account',
    'constraint': 'constraint',
    'exclude': 'exclude',
}
# Allowed keys per section; None means any key (a lookup table).
SECTIONS: dict[str, set[str] | None] = {
    'dev': {*DEV_START_KEYS, 'log_dir', 'max_allocations'},
    'cluster': {'preset', 'gpu_partitions', 'node_login'},
    'gpu-aliases': None,
    'gpu-labels': None,
}
NODE_LOGIN_METHODS = ('ssh', 'srun')


class ConfigError(Exception):
    pass


def user_config_path() -> Path:
    base = os.environ.get('XDG_CONFIG_HOME') or Path.home() / '.config'
    return Path(base) / 'allegro-buddy' / 'config.ini'


def site_config_path() -> Path:
    return Path(os.environ.get('AB_SITE_CONFIG') or '/etc/allegro-buddy/config.ini')


def preset_names() -> list[str]:
    folder = resources.files('allegro_buddy') / 'clusters'
    return sorted(
        item.name.removesuffix('.ini')
        for item in folder.iterdir()
        if item.name.endswith('.ini')
    )


def preset_text(name: str) -> str:
    return (resources.files('allegro_buddy') / 'clusters' / f'{name}.ini').read_text()


def cluster_name_cache_path() -> Path:
    # Per host: a shared $HOME can span clusters, a host never does.
    base = os.environ.get('XDG_CACHE_HOME') or Path.home() / '.cache'
    return Path(base) / 'allegro-buddy' / f'cluster-name.{socket.gethostname()}'


def slurm_cluster_name() -> str | None:
    """Slurm's `ClusterName`, cached per host since it never changes; None if unknown."""
    cache = cluster_name_cache_path()
    try:
        return cache.read_text().strip() or None
    except OSError:
        pass
    name = probe_cluster_name()
    if name:
        try:
            cache.parent.mkdir(parents=True, exist_ok=True)
            cache.write_text(name + '\n')
        except OSError:
            pass  # read-only home: just probe again next time
    return name


def probe_cluster_name() -> str | None:
    """`ClusterName` from `scontrol show config`, or None when Slurm can't say."""
    try:
        proc = subprocess.run(
            ['scontrol', 'show', 'config'], check=False, capture_output=True, text=True
        )
    except FileNotFoundError:
        return None
    match = re.search(r'^ClusterName\s*=\s*(\S+)', proc.stdout or '', re.MULTILINE)
    return match.group(1) if proc.returncode == 0 and match else None


def normalize_gpu_type(name: str) -> str:
    """`RTX-A5000` -> `rtx_a5000`: how GPU types are compared everywhere."""
    return re.sub(r'[^a-z0-9]+', '_', name.lower()).strip('_')


def normalize_key(section: str, key: str) -> str:
    if SECTIONS.get(section) is None:
        return key.strip().lower()
    return key.strip().lower().replace('-', '_')


def parse_layer(text: str, source: str) -> dict[tuple[str, str], str]:
    parser = configparser.ConfigParser(
        interpolation=None, inline_comment_prefixes=('#', ';')
    )
    try:
        parser.read_string(text, source=source)
    except configparser.Error as exc:
        raise ConfigError(f'cannot parse {source}: {exc}') from exc
    values: dict[tuple[str, str], str] = {}
    for section in parser.sections():
        if section not in SECTIONS:
            raise ConfigError(
                f'unknown section [{section}] in {source}; choose from {sorted(SECTIONS)}'
            )
        allowed = SECTIONS[section]
        for raw_key, value in parser.items(section):
            key = normalize_key(section, raw_key)
            if allowed is not None and key not in allowed:
                raise ConfigError(
                    f'unknown key {raw_key!r} in [{section}] of {source}; '
                    f'choose from {sorted(allowed)}'
                )
            values[section, key] = value.strip()
    return values


def read_file_layer(path: Path) -> dict[tuple[str, str], str]:
    try:
        text = path.read_text()
    except FileNotFoundError:
        return {}
    except OSError as exc:
        raise ConfigError(f'cannot read {path}: {exc}') from exc
    return parse_layer(text, str(path))


@dataclass(frozen=True)
class Settings:
    preset: str | None
    preset_reason: str
    # (section, key) -> (value, source); later layers already won.
    values: dict[tuple[str, str], tuple[str, str]] = field(default_factory=dict)

    def get(self, section: str, key: str, default: str | None = None) -> str | None:
        entry = self.values.get((section, key))
        return entry[0] if entry else default

    def get_list(self, section: str, key: str) -> list[str]:
        raw = self.get(section, key) or ''
        return [item.strip() for item in raw.split(',') if item.strip()]

    def section(self, section: str) -> dict[str, str]:
        return {
            key: value for (sec, key), (value, _) in self.values.items() if sec == section
        }

    @cached_property
    def gpu_aliases(self) -> dict[str, str]:
        return {
            normalize_gpu_type(alias): normalize_gpu_type(target)
            for alias, target in self.section('gpu-aliases').items()
        }

    @cached_property
    def gpu_labels(self) -> dict[str, str]:
        """Canonical GPU type -> display label, in configured (display) order."""
        return {
            normalize_gpu_type(gpu_type): label
            for gpu_type, label in self.section('gpu-labels').items()
        }


def pick_preset(file_choice: str | None) -> tuple[str | None, str]:
    """Return (preset name or None, why), validating explicit choices."""
    env_choice = os.environ.get('AB_CLUSTER')
    for choice, why in ((env_choice, '$AB_CLUSTER'), (file_choice, '[cluster] preset')):
        if not choice:
            continue
        if choice == 'none':
            return None, f'disabled by {why}'
        if choice not in preset_names():
            raise ConfigError(
                f'unknown cluster preset {choice!r} from {why}; '
                f'choose from {preset_names()} or none'
            )
        return choice, f'set by {why}'
    cluster = slurm_cluster_name()
    if cluster is None:
        return None, 'Slurm did not report a ClusterName'
    if cluster in preset_names():
        return cluster, f'Slurm ClusterName is {cluster}'
    return None, f'no preset ships for Slurm ClusterName {cluster}'


@functools.cache
def load() -> Settings:
    site_path, user_path = site_config_path(), user_config_path()
    site, user = read_file_layer(site_path), read_file_layer(user_path)
    file_choice = user.get(('cluster', 'preset')) or site.get(('cluster', 'preset'))
    preset, reason = pick_preset(file_choice)

    layers = [('site file', site), ('user file', user)]
    if preset:
        source = f'preset {preset}'
        layers.insert(0, (source, parse_layer(preset_text(preset), source)))
    values = {
        key: (value, source) for source, layer in layers for key, value in layer.items()
    }
    settings = Settings(preset=preset, preset_reason=reason, values=values)
    validate(settings)
    return settings


def validate(settings: Settings) -> None:
    login = settings.get('cluster', 'node_login')
    if login is not None and login not in NODE_LOGIN_METHODS:
        raise ConfigError(
            f'[cluster] node-login must be one of {list(NODE_LOGIN_METHODS)}, got {login!r}'
        )
    limit = settings.get('dev', 'max_allocations')
    if limit is not None and not (limit.isdigit() and int(limit) >= 1):
        raise ConfigError(
            f'[dev] max-allocations must be a whole number >= 1, got {limit!r}'
        )
