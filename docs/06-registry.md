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
# Default credentials for registry.zebroo.de:
# User: admin
# Password: zebroo
```

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
