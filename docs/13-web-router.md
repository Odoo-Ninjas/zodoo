# Web Router (nginx reverse proxy)

The host-wide nginx reverse proxy that puts domains in front of Odoo instances
and other services — formerly set up by the `ansible-web_router` role.

It runs as its **own** docker-compose stack, separate from the per-project odoo
stack, and is deliberately not touched by `odoo up` / `odoo down` /
`odoo restart`. Steer it explicitly with `odoo router …`.

Two install modes:

| Mode              | Install dir                   | Use                         |
| ----------------- | ----------------------------- | --------------------------- |
| `--global`        | `/opt/proxy`                  | the host-wide router        |
| project (default) | `<WORKING_DIR>/.odoo/router/` | one router for this project |

## Commands

```bash
odoo router setup --global                    # install or update the stack
odoo router setup --global --vhosts-file f.yml  # replace vhosts.yml wholesale

odoo router vhost list --global               # what is configured
odoo router vhost show --global <domain>      # one vhost as YAML
odoo router vhost new --global                # wizard (see below)
odoo router vhost add --global <file>.yml     # one vhost from a file
odoo router vhost remove --global <domain>

odoo router apply-vhosts --global             # re-render + reload nginx
odoo router ssl --global                      # issue certs (certbot + self-signed)
odoo router restart|reload|down|docker-status --global
```

## The config menu

```bash
odoo router config --global
```

A guided menu, navigated with the arrow keys: create, edit, delete and show
vhosts, render + reload, issue certificates. It stays open until you quit, and
if you leave with unsaved-but-unapplied changes it offers to apply them.

The list shows where each vhost points and marks incomplete ones:

```
  kunde.zebroo.de   [upstream_direct_odoo]  -> 192.168.77.130:6000
  grafana.zebroo.de [upstream]              -> 192.168.77.6:8080
  alt.zebroo.de     [redirect]
  broken.zebroo.de  [upstream]              (incomplete: upstream_server, timeout)
```

Editing walks the fields of the chosen vhost, with the current value as the
default. Optional fields that are not set yet are offered with a `+` and a
short explanation; clearing an optional field removes it rather than storing an
empty value.

When creating, values are suggested where that is possible: the backend address
defaults to whatever the other vhosts point at, the port to one above the
highest already in use, and the upstream name is derived from the domain.

## The single-shot wizard

`odoo router vhost new` asks for everything a vhost needs, validates it, shows
the result and offers to write and apply it.

```bash
odoo router vhost new --global
odoo router vhost new --dry-run    # only print it, touch nothing, no router needed
```

`--dry-run` is the quickest way to get a correct vhost snippet to paste
somewhere else — it does not need an installed router.

Rarely used fields (`locations`, `headers`, `before_server_conf`,
`client_max_body_size`, `rate_limit`, custom certificates) are not asked for;
add those by hand afterwards.

## vhosts.yml

Configuration lives in `<install_dir>/vhosts.yml` and is a **list** of vhosts —
the same schema as the ansible `web_router.virtual_hosts` list. JSON works just
as well: the file is read with `yaml.safe_load`, and YAML is a superset of JSON.

A complete, commented example is in
[`router_global/vhosts.example.yml`](../router_global/vhosts.example.yml).

```yaml
- template: upstream_direct_odoo
  server_name: kunde.zebroo.de
  upstream_name: kunde_odoo
  upstream_server: 192.168.77.130
  upstream_port: 6000
  timeout: 600
  use_certbot: true
```

### Templates and their required fields

| Template                    | Required                                                                      | What it is for                                                             |
| --------------------------- | ----------------------------------------------------------------------------- | -------------------------------------------------------------------------- |
| `upstream_direct_odoo`      | `server_name`, `upstream_name`, `upstream_server`, `upstream_port`, `timeout` | An Odoo instance. Also creates the chat/longpolling upstream on port 8072. |
| `upstream`                  | same as above                                                                 | Any other service behind the proxy.                                        |
| `redirect`                  | `server_name`, `redirect_to`                                                  | Redirect to another address.                                               |
| `static_files`              | `server_name`, `folder`                                                       | Serve a directory.                                                         |
| `existing_ssl_certificates` | `server_name`                                                                 | Certificate block only, no backend.                                        |

With a custom certificate (`ssl_key_is_on_destination` or `ssl_server_cert`)
`certificate_name` becomes required as well — it is the directory name under
`/etc/ssl/custom_ssl/`.

### Optional fields

| Field                                        | Type       | Meaning                                                                                                                               |
| -------------------------------------------- | ---------- | ------------------------------------------------------------------------------------------------------------------------------------- |
| `use_certbot`                                | bool       | `odoo router ssl` issues a Let's Encrypt certificate for it.                                                                          |
| `ssl_self_signed`                            | bool       | Terminate TLS with a self-signed certificate (no Let's Encrypt / ACME). See [Offline / self-signed](#offline--self-signed-tls).       |
| `filename`                                   | string     | File name under `sites-enabled` (default: `server_name`).                                                                             |
| `allowed_ips`                                | **string** | Only these networks reach the vhost, everything else gets 403. Comma or semicolon separated — _not_ a list. The ACME path stays open. |
| `allowlist_public_paths`                     | **string** | Paths that stay reachable despite the allowlist, e.g. an API that authenticates itself. Same separator rules.                         |
| `basic_auth`                                 | **dict**   | `user: password` in clear text; hashed into `htpasswd/` with `openssl passwd -apr1`.                                                  |
| `rate_limit`                                 | string     | Per-IP rate limit in nginx syntax, e.g. `30r/m`.                                                                                      |
| `rate_limit_burst`                           | int        | Burst allowance for the rate limit (default 20).                                                                                      |
| `client_max_body_size`                       | string     | Upload limit, default `1024M`. `0` means no limit.                                                                                    |
| `proxy_request_buffering`                    | bool       | `false` streams the body upstream instead of spooling it to disk first — for multi-gigabyte uploads.                                  |
| `upstream_scheme`                            | string     | `https` if the backend speaks TLS itself.                                                                                             |
| `locations`, `headers`, `before_server_conf` | string     | Raw nginx snippets pasted into the config.                                                                                            |

### redirect_to and paths

If `redirect_to` contains a `/`, everything lands exactly there. Without a path
the requested path is appended (`$request_uri`):

```yaml
redirect_to: zebroo.de                     # /foo  ->  zebroo.de/foo
redirect_to: zebroo.de/zebroo-experience   # /foo  ->  zebroo.de/zebroo-experience
```

## Offline / self-signed TLS

On a protected LAN the router cannot reach Let's Encrypt, so `use_certbot` will
never verify and `odoo router ssl` fails, leaving the vhost listening on port 80
only. For that case use `ssl_self_signed`:

```yaml
- template: upstream
  server_name: lan.internal.zebroo.de
  upstream_name: lan_internal
  upstream_server: 192.168.77.20
  upstream_port: 8069
  timeout: 600
  ssl_self_signed: true
```

What it does:

- The template emits `listen 443 ssl` for the vhost **and** a `listen 80`
  block that 301-redirects to `https://$host$request_uri`, so plain HTTP bounces
  to TLS instead of hitting the 444 catch-all. This now applies to **every** TLS
  vhost (`use_certbot`, `ssl_self_signed`, and the custom-cert
  `ssl_key_is_on_destination` / `ssl_server_cert` modes alike), not just
  self-signed — a pre-existing custom-cert vhost that used to get a 444 on port
  80 now gets the redirect.
- The cert + key are generated **on the host** with `openssl` when the vhost is
  applied (`apply-vhosts` / `setup` / `vhost add`) and stored in
  `custom_ssl/<name>/server.{crt,key}` — with subject CN and a `subjectAltName`
  of `server_name`, ~10 year validity. A browser will still warn (it is
  self-signed) but the TLS connection works.
- `certificate_name` is optional; when omitted it defaults to `server_name`.
- It is idempotent: if `server.crt` and `server.key` already exist in that
  directory (e.g. you put a certificate there by hand) they are kept and never
  overwritten — _provided always wins_.
- No ACME / internet / `odoo router ssl` involved; `odoo router ssl` is a
  no-op for such a vhost (it still reloads nginx).

`odoo router ssl` remains the command for `use_certbot` vhosts; it now also
ensures any `ssl_self_signed` certs are in place and reloads, so one command can
cover a mixed set.

## Things that cost time

**`upstream_name` may only contain letters, digits and underscores.** It ends
up in an nginx variable (`set $var_<name>`), so a dot or a dash produces a
config nginx refuses to load — and that only surfaces at reload time, not while
rendering. The wizard rejects such names.

**`upstream_server` is the LAN address of the machine**, not its VPN address:
the router reaches the instances over the LAN.

**A missing field used to render as an empty string.** `render_configs.py` now
renders with `StrictUndefined`, so a missing field aborts with the vhost name
and the field name. Before that, a vhost without `upstream_server` silently
produced a broken config:

```
upstream  {
    server :;
}
        proxy_pass http://$var_;
        proxy_connect_timeout   ;
```

If you are chasing an older router that behaves oddly, `nginx -t` inside the
container shows this; rendering did not.
