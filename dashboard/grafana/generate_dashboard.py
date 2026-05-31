import json

PROM = {"type": "prometheus", "uid": "prometheus"}
LOKI = {"type": "loki", "uid": "loki"}

panels = []
_id = [0]


def nid():
    _id[0] += 1
    return _id[0]


def gp(x, y, w, h):
    return {"x": x, "y": y, "w": w, "h": h}


def ts(
    title, gridpos, targets, unit=None, ds=PROM, stacking=None, legend=True
):
    fc_custom = {}
    if stacking:
        fc_custom["stacking"] = {"mode": stacking, "group": "A"}
    p = {
        "id": nid(),
        "type": "timeseries",
        "title": title,
        "datasource": ds,
        "gridPos": gridpos,
        "targets": targets,
        "fieldConfig": {
            "defaults": {"custom": fc_custom or {"drawStyle": "line"}},
            "overrides": [],
        },
        "options": {
            "legend": {
                "displayMode": "list" if legend else "hidden",
                "placement": "bottom",
            },
            "tooltip": {"mode": "multi"},
        },
    }
    if unit:
        p["fieldConfig"]["defaults"]["unit"] = unit
    return p


def stat(title, gridpos, targets, unit=None, ds=PROM, graphmode="area"):
    p = {
        "id": nid(),
        "type": "stat",
        "title": title,
        "datasource": ds,
        "gridPos": gridpos,
        "targets": targets,
        "fieldConfig": {
            "defaults": {"color": {"mode": "thresholds"}},
            "overrides": [],
        },
        "options": {
            "graphMode": graphmode,
            "colorMode": "value",
            "reduceOptions": {
                "calcs": ["lastNotNull"],
                "fields": "",
                "values": False,
            },
        },
    }
    if unit:
        p["fieldConfig"]["defaults"]["unit"] = unit
    return p


def piechart(title, gridpos, targets, ds=PROM):
    return {
        "id": nid(),
        "type": "piechart",
        "title": title,
        "datasource": ds,
        "gridPos": gridpos,
        "targets": targets,
        "options": {
            "legend": {"displayMode": "list", "placement": "right"},
            "pieType": "donut",
            "reduceOptions": {"calcs": ["lastNotNull"]},
        },
        "fieldConfig": {"defaults": {}, "overrides": []},
    }


def table(title, gridpos, targets, ds=LOKI, unit=None):
    p = {
        "id": nid(),
        "type": "table",
        "title": title,
        "datasource": ds,
        "gridPos": gridpos,
        "targets": targets,
        "options": {"showHeader": True},
        "fieldConfig": {"defaults": {}, "overrides": []},
    }
    if unit:
        p["fieldConfig"]["defaults"]["unit"] = unit
    return p


def logs(title, gridpos, expr, ds=LOKI):
    return {
        "id": nid(),
        "type": "logs",
        "title": title,
        "datasource": ds,
        "gridPos": gridpos,
        "targets": [
            {
                "refId": "A",
                "datasource": ds,
                "expr": expr,
                "queryType": "range",
            }
        ],
        "options": {
            "showTime": True,
            "wrapLogMessage": True,
            "enableLogDetails": True,
            "sortOrder": "Descending",
        },
    }


def rowp(title, y):
    return {
        "id": nid(),
        "type": "row",
        "title": title,
        "collapsed": False,
        "gridPos": gp(0, y, 24, 1),
    }


def pt(expr, refId="A", ds=PROM, legend=None, instant=False):
    t = {"refId": refId, "datasource": ds, "expr": expr}
    if legend is not None:
        t["legendFormat"] = legend
    if instant:
        t["instant"] = True
    return t


def lt(expr, refId="A", ds=LOKI, legend=None, instant=False):
    t = {
        "refId": refId,
        "datasource": ds,
        "expr": expr,
        "queryType": "instant" if instant else "range",
    }
    if legend is not None:
        t["legendFormat"] = legend
    return t


y = 0
# ---------- Row: System ----------
panels.append(rowp("System – CPU / RAM / Disk", y))
y += 1
panels.append(
    ts(
        "CPU usage per container (cores)",
        gp(0, y, 12, 8),
        [
            pt(
                'sum by (name) (rate(container_cpu_usage_seconds_total{name=~".+"}[5m]))',
                legend="{{name}}",
            )
        ],
        unit="short",
    )
)
panels.append(
    ts(
        "Memory usage per container",
        gp(12, y, 12, 8),
        [
            pt(
                'sum by (name) (container_memory_usage_bytes{name=~".+"})',
                legend="{{name}}",
            )
        ],
        unit="bytes",
    )
)
y += 8
panels.append(
    ts(
        "Filesystem usage % (host/VM)",
        gp(0, y, 8, 7),
        [
            pt(
                '100 * (1 - node_filesystem_avail_bytes{fstype!~"tmpfs|overlay"} / node_filesystem_size_bytes{fstype!~"tmpfs|overlay"})',
                legend="{{mountpoint}}",
            )
        ],
        unit="percent",
    )
)
panels.append(
    stat(
        "Filestore size",
        gp(8, y, 4, 7),
        [pt("odoo_filestore_bytes", instant=True)],
        unit="bytes",
    )
)
panels.append(
    stat(
        "DB size",
        gp(12, y, 4, 7),
        [pt("odoo_db_size_bytes", instant=True)],
        unit="bytes",
    )
)
panels.append(
    stat(
        "Web workers / cron / queue",
        gp(16, y, 8, 7),
        [
            pt(
                "odoo_workers_web",
                refId="A",
                instant=True,
                legend="web workers",
            ),
            pt(
                "odoo_max_cron_threads",
                refId="B",
                instant=True,
                legend="cron threads",
            ),
            pt(
                "odoo_queuejob_workers",
                refId="C",
                instant=True,
                legend="queue workers",
            ),
        ],
        graphmode="none",
    )
)
y += 7

# ---------- Row: Requests (Loki) ----------
panels.append(rowp("Requests & Response times", y))
y += 1
panels.append(
    ts(
        "Requests/s by status",
        gp(0, y, 12, 8),
        [
            lt(
                'sum by (status) (rate({job="nginx"} | json [1m]))',
                legend="{{status}}",
            )
        ],
        unit="reqps",
        ds=LOKI,
        stacking="normal",
    )
)
panels.append(
    ts(
        "Response time (p50 / p95 / max)",
        gp(12, y, 12, 8),
        [
            lt(
                'quantile_over_time(0.50, {job="nginx"} | json | unwrap request_time [$__interval])',
                refId="A",
                legend="p50",
            ),
            lt(
                'quantile_over_time(0.95, {job="nginx"} | json | unwrap request_time [$__interval])',
                refId="B",
                legend="p95",
            ),
            lt(
                'max_over_time({job="nginx"} | json | unwrap request_time [$__interval])',
                refId="C",
                legend="max",
            ),
        ],
        unit="s",
        ds=LOKI,
    )
)
y += 8
panels.append(
    stat(
        "Avg request rate (1m)",
        gp(0, y, 4, 6),
        [lt('sum(rate({job="nginx"} | json [1m]))', instant=True)],
        ds=LOKI,
        unit="reqps",
    )
)
panels.append(
    stat(
        "Concurrent connections",
        gp(4, y, 4, 6),
        [pt("nginx_connections_active", instant=True)],
        unit="short",
    )
)
panels.append(
    stat(
        "Avg response time (5m)",
        gp(8, y, 4, 6),
        [
            lt(
                'avg_over_time({job="nginx"} | json | unwrap request_time [5m])',
                instant=True,
            )
        ],
        ds=LOKI,
        unit="s",
    )
)
panels.append(
    piechart(
        "Requests by status (range)",
        gp(12, y, 12, 6),
        [
            lt(
                'sum by (status) (count_over_time({job="nginx"} | json [$__range]))',
                instant=True,
                legend="{{status}}",
            )
        ],
        ds=LOKI,
    )
)
y += 6

# ---------- Row: Routes (Loki) ----------
panels.append(rowp("Routes (from nginx access log)", y))
y += 1
panels.append(
    ts(
        "Response time p95 by route (top 10)",
        gp(0, y, 12, 8),
        [
            lt(
                'topk(10, quantile_over_time(0.95, {job="nginx"} | json | unwrap request_time [$__interval]) by (uri))',
                legend="{{uri}}",
            )
        ],
        unit="s",
        ds=LOKI,
    )
)
panels.append(
    table(
        "Slowest routes (p95 over range)",
        gp(12, y, 12, 8),
        [
            lt(
                'topk(15, quantile_over_time(0.95, {job="nginx"} | json | unwrap request_time [$__range]) by (uri))',
                instant=True,
            )
        ],
        unit="s",
    )
)
y += 8

# ---------- Row: Network / Disk IO ----------
panels.append(rowp("Network & Disk IO", y))
y += 1
panels.append(
    ts(
        "Network IO per container (recv/send)",
        gp(0, y, 12, 8),
        [
            pt(
                'sum by (name) (rate(container_network_receive_bytes_total{name=~".+"}[5m]))',
                refId="A",
                legend="recv {{name}}",
            ),
            pt(
                '- sum by (name) (rate(container_network_transmit_bytes_total{name=~".+"}[5m]))',
                refId="B",
                legend="send {{name}}",
            ),
        ],
        unit="Bps",
    )
)
panels.append(
    ts(
        "Disk IO (host/VM)",
        gp(12, y, 12, 8),
        [
            pt(
                "sum by (device) (rate(node_disk_read_bytes_total[5m]))",
                refId="A",
                legend="read {{device}}",
            ),
            pt(
                "- sum by (device) (rate(node_disk_written_bytes_total[5m]))",
                refId="B",
                legend="write {{device}}",
            ),
        ],
        unit="Bps",
    )
)
y += 8

# ---------- Row: Postgres ----------
panels.append(rowp("PostgreSQL", y))
y += 1
panels.append(
    ts(
        "DB connections",
        gp(0, y, 8, 7),
        [pt("odoo_db_connections", legend="connections")],
        unit="short",
    )
)
panels.append(
    ts(
        "Cache hit ratio",
        gp(8, y, 8, 7),
        [
            pt(
                "sum(rate(pg_stat_database_blks_hit[5m])) / (sum(rate(pg_stat_database_blks_hit[5m])) + sum(rate(pg_stat_database_blks_read[5m])))",
                legend="hit ratio",
            )
        ],
        unit="percentunit",
    )
)
panels.append(
    ts(
        "Transactions/s (commit/rollback)",
        gp(16, y, 8, 7),
        [
            pt(
                "sum(rate(pg_stat_database_xact_commit[5m]))",
                refId="A",
                legend="commit",
            ),
            pt(
                "sum(rate(pg_stat_database_xact_rollback[5m]))",
                refId="B",
                legend="rollback",
            ),
        ],
        unit="ops",
    )
)
y += 7

# ---------- Row: Mails ----------
panels.append(rowp("Mail", y))
y += 1
panels.append(
    ts(
        "Mail messages by type (increase/1h)",
        gp(0, y, 12, 7),
        [pt("increase(odoo_mail_messages[1h])", legend="{{message_type}}")],
        unit="short",
    )
)
panels.append(
    stat(
        "Outgoing / failed / sent mail (mail.mail)",
        gp(12, y, 12, 7),
        [
            pt(
                'odoo_mail_mail{state="outgoing"}',
                refId="A",
                instant=True,
                legend="outgoing",
            ),
            pt(
                'odoo_mail_mail{state="exception"}',
                refId="B",
                instant=True,
                legend="failed",
            ),
            pt(
                'odoo_mail_mail{state="sent"}',
                refId="C",
                instant=True,
                legend="sent",
            ),
        ],
        graphmode="none",
    )
)
y += 7

# ---------- Row: Logs / Errors ----------
panels.append(rowp("Logs & Errors", y))
y += 1
panels.append(
    stat(
        "Errors last 24h",
        gp(0, y, 6, 6),
        [
            lt(
                'sum(count_over_time({job="docker"} |~ `(?i)(error|traceback|critical)` [24h]))',
                instant=True,
            )
        ],
        ds=LOKI,
        unit="short",
    )
)
panels.append(
    ts(
        "Log lines/s by container",
        gp(6, y, 18, 6),
        [
            lt(
                'sum by (container) (rate({job="docker"}[5m]))',
                legend="{{container}}",
                ds=LOKI,
            )
        ],
        unit="short",
        ds=LOKI,
        stacking="normal",
    )
)
y += 6
panels.append(
    logs(
        "Recent errors (all containers)",
        gp(0, y, 24, 10),
        '{job="docker"} |~ `(?i)(error|traceback|critical)`',
    )
)
y += 10

dashboard = {
    "annotations": {
        "list": [
            {
                "builtIn": 1,
                "datasource": {"type": "grafana", "uid": "-- Grafana --"},
                "enable": True,
                "hide": True,
                "type": "dashboard",
            }
        ]
    },
    "editable": True,
    "graphTooltip": 1,
    "schemaVersion": 39,
    "tags": ["zodoo", "odoo"],
    "time": {"from": "now-3h", "to": "now"},
    "refresh": "30s",
    "timezone": "browser",
    "title": "zodoo – Instance Overview",
    "uid": "zodoo-overview",
    "version": 2,
    "panels": panels,
}

with open(
    "/Users/marcwimmer/.odoo/images/dashboard/grafana/dashboards/zodoo-overview.json",
    "w",
) as f:
    json.dump(dashboard, f, indent=2)
print(
    "panels:",
    len([p for p in panels if p["type"] != "row"]),
    "rows:",
    len([p for p in panels if p["type"] == "row"]),
)
