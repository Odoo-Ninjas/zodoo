"""Prometheus exporter for Odoo-specific metrics not covered by stock exporters.

Exposes (on EXPORTER_PORT, default 9333):
  - odoo_workers_web / odoo_max_cron_threads / odoo_queuejob_workers
        configured worker settings (read from the env vars the composer injects)
  - odoo_filestore_bytes
        size of ODOO_DATA_DIR/filestore/<DBNAME>, refreshed in the background
  - odoo_mail_mail{state} / odoo_mail_messages{message_type}
        mail throughput (sent/outgoing/exception; email/comment/notification)
  - odoo_queue_jobs{state} / odoo_ir_cron_active
        queue-job and cron health
  - odoo_db_up
        1 if the Odoo DB could be queried this scrape

DB-derived metrics are guarded with to_regclass() so databases without the
mail/queue_job modules simply omit those series instead of erroring.
"""

import logging
import os
import subprocess
import threading
import time

import psycopg2
from prometheus_client import start_http_server
from prometheus_client.core import REGISTRY, GaugeMetricFamily

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
)
log = logging.getLogger("odoo_metrics_exporter")

PORT = int(os.environ.get("EXPORTER_PORT", "9333"))
FILESTORE_ROOT = os.environ.get("FILESTORE_ROOT", "/opt/files")
# Filestore sizing runs `du` over the whole tree, which is heavy on large
# filestores; the size barely changes, so refresh infrequently by default.
FILESTORE_REFRESH = int(os.environ.get("EXPORTER_FILESTORE_REFRESH", "900"))
DBNAME = os.environ.get("DBNAME", "")
# Container names are "<project>_<service>" and this prometheus only scrapes
# its own exporter, so odoo_instance{project=...} carries exactly one value.
# The dashboard uses it to auto-scope every panel to this instance's
# containers (cadvisor/Loki see ALL host containers otherwise).
PROJECT = os.environ.get("PROJECT_NAME") or os.environ.get("NETWORK_NAME", "")

# Background-refreshed filestore size (du can be slow on big filestores, so we
# never run it inside a scrape).
_filestore_bytes = {"value": float("nan")}


# A single connection is kept alive across scrapes instead of reconnecting
# every 15s (avoids per-scrape connect/close churn on Postgres).
_conn = {"c": None}
# prometheus_client serves /metrics from a threaded HTTP server, so overlapping
# scrapes can call collect() concurrently; the shared connection above is not
# thread-safe, so all DB access is serialized with this lock.
_db_lock = threading.Lock()


def _connect():
    return psycopg2.connect(
        host=os.environ.get("DB_HOST", "postgres"),
        port=int(os.environ.get("DB_PORT", "5432")),
        user=os.environ.get("DB_USER", "odoo"),
        password=os.environ.get("DB_PWD", "odoo"),
        dbname=DBNAME or os.environ.get("DB_USER", "odoo"),
        connect_timeout=5,
    )


def _get_conn():
    """Return a live autocommit connection, (re)connecting if needed."""
    c = _conn["c"]
    if c is not None and getattr(c, "closed", 1) == 0:
        try:
            with c.cursor() as cur:
                cur.execute("SELECT 1")
            return c
        except Exception:  # noqa: BLE001 -- stale connection, drop & reconnect
            _close_conn()
    conn = _connect()
    conn.autocommit = True
    _conn["c"] = conn
    return conn


def _close_conn():
    c = _conn["c"]
    _conn["c"] = None
    if c is not None:
        try:
            c.close()
        except Exception:  # noqa: BLE001
            pass


def _table_exists(cur, name):
    cur.execute("SELECT to_regclass(%s) IS NOT NULL", (f"public.{name}",))
    return cur.fetchone()[0]


def _filestore_loop():
    path = (
        os.path.join(FILESTORE_ROOT, "filestore", DBNAME)
        if DBNAME
        else FILESTORE_ROOT
    )
    while True:
        try:
            if os.path.isdir(path):
                out = subprocess.run(
                    ["du", "-sb", path],
                    capture_output=True,
                    text=True,
                    timeout=600,
                )
                if out.returncode == 0 and out.stdout.split():
                    _filestore_bytes["value"] = float(out.stdout.split()[0])
            else:
                _filestore_bytes["value"] = 0.0
        except Exception as exc:  # noqa: BLE001
            log.warning("filestore du failed for %s: %s", path, exc)
        time.sleep(FILESTORE_REFRESH)


def _float_env(name):
    try:
        return float(os.environ[name])
    except (KeyError, TypeError, ValueError):
        return float("nan")


def _queuejob_workers():
    # ODOO_QUEUEJOBS_CHANNELS looks like "root:1" or "root:2,foo:4"
    raw = os.environ.get("ODOO_QUEUEJOBS_CHANNELS", "")
    total = 0.0
    for part in raw.split(","):
        part = part.strip()
        if ":" in part:
            try:
                total += float(part.rsplit(":", 1)[-1])
            except ValueError:
                pass
    return total


class OdooCollector:
    def collect(self):
        g = GaugeMetricFamily(
            "odoo_workers_web", "Configured Odoo web workers"
        )
        g.add_metric([], _float_env("ODOO_WORKERS_WEB"))
        yield g

        g = GaugeMetricFamily(
            "odoo_max_cron_threads", "Configured Odoo cron threads"
        )
        g.add_metric([], _float_env("ODOO_MAX_CRON_THREADS"))
        yield g

        g = GaugeMetricFamily(
            "odoo_queuejob_workers",
            "Sum of configured queue-job channel capacities",
        )
        g.add_metric([], _queuejob_workers())
        yield g

        inst = GaugeMetricFamily(
            "odoo_instance",
            "Static info about this instance; the dashboard uses its "
            "project label to auto-scope panels to this instance's containers",
            labels=["project"],
        )
        inst.add_metric([PROJECT], 1.0)
        yield inst

        g = GaugeMetricFamily(
            "odoo_filestore_bytes", "Filestore size in bytes"
        )
        g.add_metric([], _filestore_bytes["value"])
        yield g

        mail_mail = GaugeMetricFamily(
            "odoo_mail_mail", "mail.mail rows by state", labels=["state"]
        )
        mail_msg = GaugeMetricFamily(
            "odoo_mail_messages",
            "mail.message rows by type",
            labels=["message_type"],
        )
        qjob = GaugeMetricFamily(
            "odoo_queue_jobs", "queue.job rows by state", labels=["state"]
        )
        cron_active = GaugeMetricFamily(
            "odoo_ir_cron_active", "Number of active ir.cron jobs"
        )
        up = GaugeMetricFamily(
            "odoo_db_up", "1 if the exporter could query the Odoo DB"
        )
        # Serialize DB access: the threaded /metrics server can run collect()
        # concurrently and the connection above is shared.
        _db_lock.acquire()
        try:
            conn = _get_conn()
            cur = conn.cursor()
            up.add_metric([], 1.0)
            if _table_exists(cur, "mail_mail"):
                cur.execute(
                    "SELECT COALESCE(state, 'unknown'), count(*) "
                    "FROM mail_mail GROUP BY 1"
                )
                for state, cnt in cur.fetchall():
                    mail_mail.add_metric([str(state)], float(cnt))
            if _table_exists(cur, "mail_message"):
                cur.execute(
                    "SELECT COALESCE(message_type, 'unknown'), count(*) "
                    "FROM mail_message GROUP BY 1"
                )
                for mtype, cnt in cur.fetchall():
                    mail_msg.add_metric([str(mtype)], float(cnt))
            if _table_exists(cur, "queue_job"):
                cur.execute(
                    "SELECT COALESCE(state, 'unknown'), count(*) "
                    "FROM queue_job GROUP BY 1"
                )
                for state, cnt in cur.fetchall():
                    qjob.add_metric([str(state)], float(cnt))
            if _table_exists(cur, "ir_cron"):
                cur.execute("SELECT count(*) FROM ir_cron WHERE active")
                cron_active.add_metric([], float(cur.fetchone()[0]))
            cur.close()
        except Exception as exc:  # noqa: BLE001
            log.warning("db scrape failed: %s", exc)
            up.add_metric([], 0.0)
            # drop the (possibly broken) connection so the next scrape reconnects
            _close_conn()
        finally:
            _db_lock.release()

        yield up
        yield mail_mail
        yield mail_msg
        yield qjob
        yield cron_active


def main():
    threading.Thread(target=_filestore_loop, daemon=True).start()
    REGISTRY.register(OdooCollector())
    start_http_server(PORT)
    log.info("odoo_metrics_exporter listening on :%s (db=%s)", PORT, DBNAME)
    while True:
        time.sleep(3600)


if __name__ == "__main__":
    main()
