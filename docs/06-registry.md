# Using the Docker Registry

zodoo can push and pull all Docker images (including base images like postgres, redis, etc.) to/from a private Docker registry. This speeds up deployments on production systems — no local builds needed.

## Push (build server / developer machine)

### 1. Configure the registry URL

```bash
odoo setting HUB_URL registry.zebroo.de:443/myprojectname
odoo setting DOCKER_IMAGE_TAG latest
```

### 2. Login

```bash
odoo docker-registry login
```

There are no shared default credentials for registry.zebroo.de — every user has
their own account. You only need one to **push**; see
[Pulling needs no account](#pulling-needs-no-account) below.

`odoo build` asks for an account at the point where it would upload something,
and stores user and password in `~/.odoo/settings`. A freshly requested account
can read but not write yet — ask an admin for push rights at
https://registry.zebroo.de/admin.

Note that `docker login` cannot tell you whether your credentials are correct:
registry.zebroo.de answers the version endpoint without a challenge (that is
what makes anonymous pulling possible), so the client reports success for any
password. zodoo checks the credentials itself against an endpoint that is still
protected and says so when they are rejected.

### 3. Build images

```bash
odoo build
```

### 4. Push

```bash
odoo regpush
```

All images (Odoo, postgres, proxy, etc.) are pushed. Image tags include a SHA-based identifier.

---

## Pull (production / target system)

### 1. Configure the same registry URL and enable registry mode

```bash
odoo setting HUB_URL registry.zebroo.de:443/myprojectname
odoo setting REGISTRY 1
odoo setting DOCKER_IMAGE_TAG latest
```

`REGISTRY=1` rewrites all image references to point to `HUB_URL` and disables local builds.

### 2. Login

```bash
odoo docker-registry login
```

### 3. Pull

```bash
odoo regpull
```

### 4. Start

```bash
odoo up -d
```

---

## Pulling needs no account

Separate from the project images above, zodoo keeps a **build cache** in the
same registry, and reading from it costs nothing to set up.

`registry.zebroo.de` serves the prebuilt CPython image (`zodoo/python`)
anonymously. That is the one that matters on a fresh machine: without it, the
build compiles CPython locally, which takes about a quarter of an hour. The
registry URL already has a default, so this works with no configuration at all
— there is no question to answer and nothing to log in to.

Everything else stays behind the login: the per-service cache images
(`zodoo-*`), every project namespace, and `/v2/_catalog` — the repository
listing names customers, so it is not public.

| Setting                    | Description                                                  |
| -------------------------- | ------------------------------------------------------------ |
| `ZODOO_REGISTRY_URL`       | Default `registry.zebroo.de`                                 |
| `ZODOO_REGISTRY_USERNAME`  | Only needed for pushing                                      |
| `ZODOO_REGISTRY_PASSWORD`  | Only needed for pushing                                      |
| `ZODOO_REGISTRY_SUGGESTED` | `0` opts out completely — no pulls, no account, no questions |

Do not confuse this with the `REGISTRY=1` setting above: that one rewrites all
image references to `HUB_URL` and blocks local builds, which is meant for
production systems and would break a development machine.

---

## Self-signed certificates

If your registry uses a self-signed TLS certificate:

```bash
odoo docker-registry self-sign-hub-certificate
```

---

## Settings reference

| Setting            | Description                                                            |
| ------------------ | ---------------------------------------------------------------------- |
| `HUB_URL`          | Registry URL: `user:password@host:port/path` or `host:port/path`       |
| `REGISTRY`         | `1` = force pull from registry, block local builds (use on production) |
| `DOCKER_IMAGE_TAG` | Tag for images (e.g. `latest`, `v1.2.3`, `main`)                       |
