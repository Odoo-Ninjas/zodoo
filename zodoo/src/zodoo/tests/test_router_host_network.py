"""`odoo router setup --host-network`: the router in the host's network.

Needed where the router and the project proxy run under different docker
daemons - one unix user per instance with rootless docker, plus our root
daemon for the router on 80/443. There is no network the router could join
(`--network`), so it talks to each proxy over a port on the host, and the
proxy publishes only on 127.0.0.1 (PROXY_IP). In the host network the router
reaches 127.0.0.1 directly; from a bridge network it would need the port
open towards docker0, which the firewall (ufw: 22/80/443 only) blocks.
"""

import shutil
from pathlib import Path

import pytest
import yaml

from .. import lib_router

REPO_ROOT = Path(__file__).resolve().parents[4]
COMPOSE = REPO_ROOT / "router_global" / "files" / "docker-compose.yml"


@pytest.fixture
def install_dir(tmp_path):
    shutil.copy(COMPOSE, tmp_path / "docker-compose.yml")
    return tmp_path


def _router(install_dir):
    config = yaml.safe_load((install_dir / "docker-compose.yml").read_text())
    return config, config["services"]["router"]


def test_router_runs_in_the_host_network(install_dir):
    lib_router._patch_compose_host_network(install_dir)
    config, router = _router(install_dir)
    assert router["network_mode"] == "host"
    # compose refuses ports/networks together with network_mode: host
    assert "ports" not in router
    assert "networks" not in router
    assert "networks" not in config


def test_patch_is_idempotent(install_dir):
    lib_router._patch_compose_host_network(install_dir)
    first = (install_dir / "docker-compose.yml").read_text()
    lib_router._patch_compose_host_network(install_dir)
    assert (install_dir / "docker-compose.yml").read_text() == first


def test_rest_of_the_service_is_kept(install_dir):
    _, before = _router(install_dir)
    lib_router._patch_compose_host_network(install_dir)
    _, after = _router(install_dir)
    assert after["volumes"] == before["volumes"]
    assert after.get("build") == before.get("build")


def test_setup_offers_the_switch():
    names = {p.name for p in lib_router.setup_.params}
    assert "host_network" in names
