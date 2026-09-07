# Debug Mode

zodoo's debug mode lets you debug Python code on a **running production system** without affecting other users. Only your browser session is routed to the debug container.

## How it works

```
Your browser (with cookie)
    │
    ├─ Python requests ──→ debug container (your debugger)
    └─ Websocket/other ──→ normal odoo container (unaffected)
```

A cookie in your browser tells the proxy to route your requests to the debug container. All other users continue using the normal container.

## Setup

### 1. Make sure zodoo is up to date

```bash
odoo upgrade
```

### 2. Start the production system normally

```bash
odoo up -d
```

### 3. Start debug mode

```bash
odoo debug odoo_debug
```

Inside the container prompt that opens, type:

```
debug
```

and press ENTER. The debug container starts and attaches to your debugger.

### 4. Activate debug mode in your browser

Navigate to:

```
https://<your-system-url>/debugpython
```

This sets a cookie in your browser. From now on, your Python requests go to the debug container.

### 5. Use the system normally

Open the Odoo application in your browser. Your Python code executes in the debug container where you can set breakpoints, inspect variables, etc.

### 6. Deactivate debug mode

```
https://<your-system-url>/debugpython_off
```

This removes the cookie. Your requests go back to the normal container.

## Local debugging setup (macOS)

See [Local Odoo Development Setup on Mac](./07-mac-setup.md) for configuring VS Code / pudb for local Python debugging.

## Debug log level

Configure the log level inside the debug container:

```bash
odoo setting ODOO_DEBUG_LOGLEVEL=debug
# options: info, warning, error, debug
```
