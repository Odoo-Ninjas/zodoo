#!/usr/bin/env python3
"""Generate the provisioned Grafana dashboards.

Hand-editing multi-panel Grafana JSON is painful, so the dashboards are
generated here. After changing panels run:

    python3 dashboard/grafana/generate_dashboard.py

Grafana picks the files up automatically (file provisioning, 30s interval).

Two dashboards are produced under dashboards/:
  - zodoo-overview.json : full instance overview (reached via /system)
  - zodoo-logs.json     : searchable log explorer (reached via /logs)

Every panel is scoped to the current instance via the hidden `$project`
template variable (label_values(odoo_instance, project)). cadvisor and Loki
otherwise see ALL containers on the docker host, not just this project's.
"""

import json

PROM = {"type": "prometheus", "uid": "prometheus"}
LOKI = {"type": "loki", "uid": "loki"}

# container_name is "<project>_<service>"; Loki `container` label is the same.
CN = 'name=~"$project.*"'  # cadvisor selector
LC = 'container=~"$project.*"'  # Loki selector
# Core app containers only (odoo + postgres, anchored so the *_exporter and
# *_cronjobs siblings are excluded). Used for the focused Network/Disk IO row.
CORE = 'name=~"$project.*_(odoo|postgres)$"'
# Loki equivalent: the log-volume panel focuses on the containers that
# actually matter operationally (odoo app, db, reverse proxy).
LCORE = 'container=~"$project.*_(odoo|postgres|proxy)$"'

# Case-SENSITIVE level matchers. Case matters: matching a lowercase "error"
# substring would flag nginx access logs (referrer URLs containing "Errors"),
# normal words and info-level lines. Odoo/Python use ERROR/CRITICAL/Traceback,
# nginx uses [error]/[crit], Grafana/Alloy use level=error.
ERR_RE = r"ERROR|CRITICAL|Traceback|\[error\]|\[crit\]|level=error"
WARN_RE = r"WARNING|\[warn\]|level=warn"

# "Errors/Warnings last 24h" should reflect the Odoo workload, not the
# observability stack griping about itself (alloy/loki/exporters) or the proxy
# access/lua noise. Exclude those sidecars from the summary counters.
EXCL = (
    r'container!~".*(grafana|prometheus|loki|alloy|cadvisor|exporter|proxy)$"'
)

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


PROJECT_VAR = {
    "name": "project",
    "label": "Project",
    "type": "query",
    "datasource": PROM,
    "query": {"query": "label_values(odoo_instance, project)", "refId": "x"},
    "definition": "label_values(odoo_instance, project)",
    "refresh": 1,
    "sort": 1,
    "includeAll": False,
    "multi": False,
    "hide": 2,
    "current": {},
}


def dashboard(title, uid, panels, extra_vars=None):
    return {
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
        "templating": {"list": [PROJECT_VAR] + (extra_vars or [])},
        "time": {"from": "now-3h", "to": "now"},
        "refresh": "30s",
        "timezone": "browser",
        "title": title,
        "uid": uid,
        "version": 4,
        "panels": panels,
    }


def write(name, dash):
    path = (
        "/Users/marcwimmer/.odoo/images/dashboard/grafana/dashboards/"
        + name
        + ".json"
    )
    with open(path, "w") as f:
        json.dump(dash, f, indent=2)
    print(
        name,
        "->",
        len([p for p in dash["panels"] if p["type"] != "row"]),
        "panels",
    )


# =========================================================================
# Dashboard 1: overview  (/system)   ASCII hyphen -> clean slug
# =========================================================================
_id[0] = 0
panels = []
y = 0
panels.append(rowp("System - CPU / RAM / Disk", y))
y += 1
panels.append(
    ts(
        "CPU usage per container (cores)",
        gp(0, y, 12, 8),
        [
            pt(
                "sum by (name) (rate(container_cpu_usage_seconds_total{%s}[5m]))"
                % CN,
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
                "sum by (name) (container_memory_usage_bytes{%s})" % CN,
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

# The dashboard's own pages (Grafana under /system, the log explorers under
# /logs and /logs2) generate constant auto-refresh self-traffic that would
# otherwise dominate the route stats. A *line* filter on the raw nginx-JSON
# field is used (a `| uri !~` label filter after `| json` does NOT reliably
# drop them in Loki); it must sit before `| json`. The prefix match covers
# /system/api/..., /logs/... and /logs2 too.
ROUTE_EXCL = '!~ `"uri":"/(system|logs)`'
panels.append(rowp("Routes (from nginx access log)", y))
y += 1
panels.append(
    ts(
        "Response time p95 by route (top 10)",
        gp(0, y, 12, 8),
        [
            lt(
                'topk(10, quantile_over_time(0.95, {job="nginx"} %s | json | unwrap request_time [$__interval]) by (uri))'
                % ROUTE_EXCL,
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
                'topk(15, quantile_over_time(0.95, {job="nginx"} %s | json | unwrap request_time [$__range]) by (uri))'
                % ROUTE_EXCL,
                instant=True,
            )
        ],
        unit="s",
    )
)
y += 8

panels.append(rowp("Network & Disk IO (odoo / postgres)", y))
y += 1
panels.append(
    ts(
        "Network IO odoo / postgres (recv/send)",
        gp(0, y, 12, 8),
        [
            pt(
                "sum by (name) (rate(container_network_receive_bytes_total{%s}[5m]))"
                % CORE,
                refId="A",
                legend="recv {{name}}",
            ),
            pt(
                "- sum by (name) (rate(container_network_transmit_bytes_total{%s}[5m]))"
                % CORE,
                refId="B",
                legend="send {{name}}",
            ),
        ],
        unit="Bps",
    )
)
panels.append(
    ts(
        "Disk IO odoo / postgres (read/write)",
        gp(12, y, 12, 8),
        [
            pt(
                "sum by (name) (rate(container_fs_reads_bytes_total{%s}[5m]))"
                % CORE,
                refId="A",
                legend="read {{name}}",
            ),
            pt(
                "- sum by (name) (rate(container_fs_writes_bytes_total{%s}[5m]))"
                % CORE,
                refId="B",
                legend="write {{name}}",
            ),
        ],
        unit="Bps",
    )
)
y += 8

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
                "rate(odoo_db_activity_blks_hit[5m]) / (rate(odoo_db_activity_blks_hit[5m]) + rate(odoo_db_activity_blks_read[5m]))",
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
                "rate(odoo_db_activity_xact_commit[5m])",
                refId="A",
                legend="commit",
            ),
            pt(
                "rate(odoo_db_activity_xact_rollback[5m])",
                refId="B",
                legend="rollback",
            ),
        ],
        unit="ops",
    )
)
y += 7

panels.append(rowp("Background jobs (queue & cron)", y))
y += 1
# DB reachability as a coloured UP/DOWN stat (exporter's odoo_db_up).
panels.append(
    stat(
        "DB reachable",
        gp(0, y, 4, 6),
        [pt("odoo_db_up", instant=True)],
        graphmode="none",
    )
)
panels[-1]["fieldConfig"]["defaults"]["mappings"] = [
    {
        "type": "value",
        "options": {
            "0": {"text": "DOWN", "color": "red", "index": 0},
            "1": {"text": "UP", "color": "green", "index": 1},
        },
    }
]
panels[-1]["fieldConfig"]["defaults"]["thresholds"] = {
    "mode": "absolute",
    "steps": [
        {"color": "red", "value": None},
        {"color": "green", "value": 1},
    ],
}
panels.append(
    stat(
        "Active cron jobs",
        gp(4, y, 4, 6),
        [pt("odoo_ir_cron_active", instant=True)],
        unit="short",
        graphmode="none",
    )
)
# Failed queue jobs: green at 0, red as soon as anything failed. Empty on
# instances without the queue_job module (panel shows "No data").
panels.append(
    stat(
        "Queue jobs failed",
        gp(8, y, 4, 6),
        [pt('odoo_queue_jobs{state=~"failed"}', instant=True)],
        unit="short",
        graphmode="none",
    )
)
panels[-1]["fieldConfig"]["defaults"]["thresholds"] = {
    "mode": "absolute",
    "steps": [
        {"color": "green", "value": None},
        {"color": "red", "value": 1},
    ],
}
panels.append(
    ts(
        "Queue jobs by state",
        gp(12, y, 12, 6),
        [pt("odoo_queue_jobs", legend="{{state}}")],
        unit="short",
    )
)
y += 6

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

panels.append(rowp("Logs & Errors", y))
y += 1
panels.append(
    stat(
        "Errors last 24h",
        gp(0, y, 6, 6),
        [
            lt(
                'sum(count_over_time({job="docker", %s, %s} |~ `%s` [24h]))'
                % (LC, EXCL, ERR_RE),
                instant=True,
            )
        ],
        ds=LOKI,
        unit="short",
    )
)
panels.append(
    ts(
        "Log lines/s by container (odoo / postgres / proxy)",
        gp(6, y, 18, 6),
        [
            lt(
                'sum by (container) (rate({job="docker", %s}[5m]))' % LCORE,
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
        "Recent errors (this instance)",
        gp(0, y, 24, 10),
        f'{{job="docker", {LC}, {EXCL}}} |~ `{ERR_RE}`',
    )
)
y += 10

write(
    "zodoo-overview",
    dashboard("zodoo - Instance Overview", "zodoo-overview", panels),
)

# =========================================================================
# Dashboard 2: logs  (/logs) — searchable log explorer, replaces log.io
# =========================================================================
# Interactive filters (Graylog-style). Grafana custom-variable syntax is
# "Display : value", so the value is the actual (case-sensitive) regex used in
# the line filter. "All" -> "." matches every line.
LOGS_VARS = [
    {
        "name": "search",
        "label": "Search (regex, case-insensitive)",
        "type": "textbox",
        "query": "",
        "current": {"text": "", "value": ""},
        "options": [{"text": "", "value": "", "selected": True}],
        "hide": 0,
    },
    {
        "name": "container",
        "label": "Container",
        "type": "query",
        "datasource": LOKI,
        "query": 'label_values({job="docker", container=~"$project.*"}, container)',
        "definition": 'label_values({job="docker", container=~"$project.*"}, container)',
        "refresh": 1,
        "sort": 1,
        "includeAll": True,
        "allValue": ".+",
        # single-select: a multi-select leaves "All" co-selected on the first
        # click, so picking one container still matches everything (.+).
        "multi": False,
        "current": {"text": "All", "value": "$__all", "selected": True},
        "hide": 0,
    },
    {
        "name": "level",
        "label": "Level",
        "type": "custom",
        "query": "All : ., Errors : %s, Warnings : %s, Info : INFO|\\[info\\]|level=info"
        % (ERR_RE, WARN_RE),
        "includeAll": False,
        "multi": False,
        "current": {"text": "All", "value": ".", "selected": True},
        "options": [
            {"text": "All", "value": ".", "selected": True},
            {"text": "Errors", "value": ERR_RE, "selected": False},
            {"text": "Warnings", "value": WARN_RE, "selected": False},
            {
                "text": "Info",
                "value": "INFO|\\[info\\]|level=info",
                "selected": False,
            },
        ],
        "hide": 0,
    },
]

# Selector honouring project scope + all three filters.
#   search : case-INsensitive free text  (empty -> matches all)
#   level  : case-SENSITIVE level regex   (All -> "." matches all)
SEL = (
    '{job="docker", container=~"$project.*", container=~"$container"}'
    " |~ `(?i)$search` |~ `$level`"
)

_id[0] = 0
p = []
y = 0
p.append(
    stat(
        "Errors last 24h",
        gp(0, y, 5, 4),
        [
            lt(
                'sum(count_over_time({job="docker", %s, %s} |~ `%s` [24h]))'
                % (LC, EXCL, ERR_RE),
                instant=True,
            )
        ],
        ds=LOKI,
        unit="short",
    )
)
p.append(
    stat(
        "Warnings last 24h",
        gp(5, y, 5, 4),
        [
            lt(
                'sum(count_over_time({job="docker", %s, %s} |~ `%s` [24h]))'
                % (LC, EXCL, WARN_RE),
                instant=True,
            )
        ],
        ds=LOKI,
        unit="short",
    )
)
p.append(
    ts(
        "Matching log volume by container",
        gp(10, y, 14, 4),
        [
            lt(
                "sum by (container) (count_over_time(%s [$__interval]))" % SEL,
                legend="{{container}}",
            )
        ],
        unit="short",
        ds=LOKI,
        stacking="normal",
    )
)
y += 4
p.append(
    logs(
        "Logs  -  Search (regex) / Container / Level filters above apply live",
        gp(0, y, 24, 24),
        SEL,
    )
)
y += 24

write(
    "zodoo-logs",
    dashboard("zodoo - Logs", "zodoo-logs", p, extra_vars=LOGS_VARS),
)
