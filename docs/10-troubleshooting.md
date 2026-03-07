# Troubleshooting

## General

### Check project status
```bash
odoo setup status
```

### View container logs
```bash
docker logs <project_name>_odoo_1 --tail 100 -f
```

### Rebuild everything from scratch
```bash
odoo down
odoo build
odoo -f db reset
odoo up -d
```

---

## Installation Issues

### Previous wodoo installation
```bash
rm -Rf ~/.odoo/images
bash <(curl -fsSL https://raw.githubusercontent.com/Odoo-Ninjas/zodoo/refs/heads/main/install.sh)
```

### `odoo` command not found after installation
```bash
# Make sure pipx bin dir is in PATH:
pipx ensurepath
source ~/.bashrc  # or ~/.zshrc
```

---

## Startup Issues

### Port already in use
```bash
odoo setup next-port    # assigns next free port
odoo reload
odoo up -d
```

### Containers exit immediately
Check logs:
```bash
docker logs <project_name>_odoo_1
```

Common causes:
- Missing or wrong settings → `odoo setup status`, then fix and `odoo reload`
- Database not yet initialized → `odoo -f db reset`

### `odoo reload` fails
Make sure you're in the project directory (where `.odoo/settings` or `MANIFEST` lives).

---

## Database Issues

### Broken CSS/JS after update
```bash
odoo setup remove-web-assets
# Log in as admin to regenerate
```

### Database connection refused
```bash
odoo up -d postgres   # start only postgres
odoo db pgactivity    # check if postgres is responding
```

### Reset to clean state
```bash
odoo -f db reset
```

### Restore hangs or fails
```bash
odoo db pgactivity    # check for blocking connections
odoo restart postgres
odoo -f restore odoo-db
```

---

## macOS-specific

### rsync errors
```bash
brew install rsync
```

### Docker Desktop issues
Restart Docker Desktop. Then:
```bash
odoo down
odoo up -d
```

### Python version mismatch
```bash
odoo setting ODOO_PYTHON_VERSION 3.12
odoo reload && odoo build
```

---

## Performance

### Workers and memory
```bash
odoo setting ODOO_WORKERS_WEB 4
odoo setting LIMIT_MEMORY_HARD_WEB 8053063680
odoo reload
odoo restart
```

### Profiling
```bash
pipx runpip wodoo install line_profiler
$WODOO_PYTHON -m kernprof -l -v odoo reload
```

---

## AI Assistant (Claude Code / Cursor) issues

Claude Code runs in a network sandbox. Some URLs are blocked:

- ✅ `github.com`, `pypi.org`, `npmjs.org` — accessible
- ❌ `docs.zebroo.de` — blocked (not in Anthropic's egress allowlist)

**Solution:** All documentation is available in this `docs/` folder and in `CLAUDE.md` at the project root. AI tools can read these local files directly.

If Claude Code doesn't know about zodoo commands, point it to:
- `CLAUDE.md` in your project root
- `docs/04-command-reference.md`
