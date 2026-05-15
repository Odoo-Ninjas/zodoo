import click
import inspect
import os
from pathlib import Path
import platform, re, subprocess

current_dir = Path(
    os.path.dirname(os.path.abspath(inspect.getfile(inspect.currentframe())))
)


def after_compose(config, settings, yml, globals):
    # set postgres version
    V = settings["POSTGRES_VERSION"]
    if "postgres" in yml["services"] and yml["services"]["postgres"].get(
        "build"
    ):
        yml["services"]["postgres"]["build"]["dockerfile"] = f"Dockerfile.{V}"

    # if a named postgres volume is used, make it as external with name
    if settings["NAMED_ODOO_POSTGRES_VOLUME"]:
        yml["volumes"]["odoo_postgres_volume"] = {
            "external": True,
            "name": settings["NAMED_ODOO_POSTGRES_VOLUME"],
        }

    candidates = {
        "/config1": "~/.odoo/postgres.conf",
        "/config2": f"~/.odoo/{settings['PROJECT_NAME']}/postgres.conf",
    }
    custom_config = False
    for target, source_path in candidates.items():
        candi_path = Path(source_path).expanduser()
        if candi_path.is_file():
            yml["services"]["postgres"]["volumes"].append(
                {
                    "type": "bind",
                    "source": str(candi_path),
                    "target": str(target),
                }
            )
            click.secho(
                f"Using postgres config from {candi_path}", fg="yellow"
            )
            custom_config = True
        else:
            click.secho(
                f"Suggestion: you can put postgres configuration file here: {candi_path}",
                fg="blue",
            )

    if not custom_config:
        click.secho(
            """
8888888b.   .d88888b.   .d8888b. 88888888888 .d8888b.  8888888b.  8888888888 .d8888b.        .d8888b.  8888888888 88888888888 88888888888 8888888 888b    888  .d8888b.   .d8888b.
888   Y88b d88P" "Y88b d88P  Y88b    888    d88P  Y88b 888   Y88b 888       d88P  Y88b      d88P  Y88b 888            888         888       888   8888b   888 d88P  Y88b d88P  Y88b
888    888 888     888 Y88b.         888    888    888 888    888 888       Y88b.           Y88b.      888            888         888       888   88888b  888 888    888 Y88b.
888   d88P 888     888  "Y888b.      888    888        888   d88P 8888888    "Y888b.         "Y888b.   8888888        888         888       888   888Y88b 888 888         "Y888b.
8888888P"  888     888     "Y88b.    888    888  88888 8888888P"  888           "Y88b.          "Y88b. 888            888         888       888   888 Y88b888 888  88888     "Y88b.
888        888     888       "888    888    888    888 888 T88b   888             "888            "888 888            888         888       888   888  Y88888 888    888       "888
888        Y88b. .d88P Y88b  d88P    888    Y88b  d88P 888  T88b  888       Y88b  d88P      Y88b  d88P 888            888         888       888   888   Y8888 Y88b  d88P Y88b  d88P
888         "Y88888P"   "Y8888P"     888     "Y8888P88 888   T88b 8888888888 "Y8888P"        "Y8888P"  8888888888     888         888     8888888 888    Y888  "Y8888P88  "Y8888P"
        """,
            fg="yellow",
        )

        click.secho("Suggested configuration file: postgres.conf", fg="blue")
        suggest_postgres_conf()
        click.secho(80 * "-", fg="yellow")
        click.secho(
            "Please tune your system!! Create the file ~/.odoo/postgres.conf - i will annoy you for your sake",
            fg="red",
        )


def suggest_postgres_conf(
    workload="oltp", max_connections: int = 100, pg_version: int = 17
):
    """
    workload: 'oltp', 'mixed' oder 'olap'
    max_connections: erwartete maximale Verbindungen
    pg_version: nur Info im Header
    """

    def human_bytes(num_bytes: int) -> str:
        gb = 1024**3
        mb = 1024**2
        if num_bytes % gb == 0:
            return f"{num_bytes // gb}GB"
        return f"{max(1, num_bytes // mb)}MB"

    def read_file(path: str):
        try:
            with open(path) as f:
                return f.read()
        except Exception:
            return None

    # --- RAM erkennen ---
    total_ram = 8 * 1024**3  # fallback 8GB
    if platform.system() == "Linux":
        data = read_file("/proc/meminfo")
        if data:
            m = re.search(r"MemTotal:\s+(\d+)\s+kB", data)
            if m:
                total_ram = int(m.group(1)) * 1024
    elif platform.system() == "Darwin":
        try:
            out = subprocess.check_output(
                ["sysctl", "-n", "hw.memsize"], text=True
            ).strip()
            total_ram = int(out)
        except Exception:
            pass

    # --- CPU Kerne ---
    cores = os.cpu_count() or 1

    # --- SSD ja/nein ---
    ssd = None
    if platform.system() == "Linux":
        try:
            mounts = read_file("/proc/self/mounts") or ""
            root_line = next(
                (ln for ln in mounts.splitlines() if " / " in ln), ""
            )
            dev = root_line.split()[0] if root_line else ""
            base = re.sub(r"p?\d+$", "", os.path.basename(dev))
            rot_path = f"/sys/block/{base}/queue/rotational"
            val = read_file(rot_path)
            if val is not None:
                ssd = val.strip() == "0"
        except Exception:
            pass
    elif platform.system() == "Darwin":
        ssd = True

    # --- Heuristik ---
    if workload == "oltp":
        buf_frac, cache_frac, workmem_pool_frac = 0.25, 0.70, 0.10
    elif workload == "olap":
        buf_frac, cache_frac, workmem_pool_frac = 0.30, 0.70, 0.25
    else:  # mixed
        buf_frac, cache_frac, workmem_pool_frac = 0.28, 0.70, 0.15

    shared_buffers = int(total_ram * buf_frac)
    effective_cache_size = int(total_ram * cache_frac)
    maintenance_work_mem = int(min(total_ram * 0.05, 2 * 1024**3))
    consumers = max_connections * (2.0 if workload == "olap" else 1.5)
    work_mem = max(
        4 * 1024**2, int(total_ram * workmem_pool_frac) // int(consumers)
    )

    max_wal_size = 4 * 1024**3 if (ssd or cores >= 8) else 2 * 1024**3
    min_wal_size = max_wal_size // 4

    settings = {
        "shared_buffers": human_bytes(shared_buffers),
        "effective_cache_size": human_bytes(effective_cache_size),
        "work_mem": human_bytes(work_mem),
        "maintenance_work_mem": human_bytes(maintenance_work_mem),
        "max_connections": str(2000),
        "checkpoint_completion_target": "0.9",
        "max_wal_size": human_bytes(max_wal_size),
        "min_wal_size": human_bytes(min_wal_size),
        "wal_compression": "on" if cores >= 4 else "off",
        "random_page_cost": "1.1" if ssd else "2.5" if ssd is False else "1.5",
        "max_worker_processes": str(min(cores, 32)),
        "max_parallel_workers": str(min(cores, 32)),
        "max_parallel_workers_per_gather": str(max(1, cores // 2)),
    }

    # --- Ausgabe ---
    print(f"# Suggested postgresql.conf for PostgreSQL {pg_version}")
    print(
        f"# System: RAM={human_bytes(total_ram)}, cores={cores}, SSD={ssd}, workload={workload}"
    )
    for k, v in settings.items():
        click.secho(f"{k} = {v}", fg="yellow")

    return settings
