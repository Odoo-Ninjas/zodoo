# Robot Tests

Robot tests are browser-driven acceptance tests: they drive a real Odoo in a
real browser and assert on what a user would see. zodoo provides the tooling to
create and run them locally; zCICD runs the same tests in CI.

## Setting up a project

One command does the whole setup:

```bash
odoo robot setup
```

It is idempotent — safe to run again on a project that is already set up.

`odoo robot setup` performs every step that used to be done by hand:

1. Adds `odoo-robot_utils` to `gimera.yml` if it is not already there:

   ```yaml
   - branch: main
     path: addons_robot
     type: integrated
     url: git@github.com:Odoo-Ninjas/odoo-robot_utils
   ```

2. Adds `robot_utils` to the `install` list in `MANIFEST`.
3. Adds `addons_robot` to `addons_paths` in `MANIFEST`.
4. Creates a Robot Framework virtualenv at `~/.robotenv` and installs the
   requirements into it.
5. Runs `gimera apply` recursively, with update and missing-only, to fetch the
   repository.

:::note
Before running it, make sure your modules install cleanly on an empty database:

```bash
odoo -f db reset
odoo update
```
:::

## Creating a test

```bash
odoo robot new smoketest
```

This copies `addons_robot/robot_utils/tests/test_template.robot` to
`tests/smoketest.robot` and prints the command to run it. It refuses to
overwrite an existing file.

`odoo robot new` invokes `odoo robot setup` first. Pass `-I`
(`--no-install-pip`) to skip that — useful when the environment is already
prepared and you just want the file.

### Anatomy of a test file

A generated test has three sections:

| Section | Purpose |
| --- | --- |
| **Settings** | Imports and configuration. Usually fine as generated |
| **Test Cases** | The tests themselves — rewrite these for your use case |
| **Keywords** | Reusable Robot functions |

Declare which modules a test needs with comments at the top of the file:

```robotframework
#odoo-require: crm,sale_stock
#odoo-uninstall: partner_autocomplete
```

zodoo reads these and prepares the database accordingly before the run.

## Running tests

```bash
odoo robot run tests/smoketest.robot
odoo robot run                          # pick from available tests
odoo robot run --all
```

Development mode is required — running robot tests aborts otherwise.

### Options

| Option | Default | Effect |
| --- | --- | --- |
| `-u`, `--user` | `admin` | Odoo user to log in as |
| `-a`, `--all` | | Run every test |
| `-n`, `--test_name` | | Run a single named test case within the file |
| `--param key=value` | | Pass variables to the test; repeatable |
| `--parallel` | `1` | Number of parallel robot runs |
| `--tags` | | Restrict to tagged tests |
| `--timeout` | `20` | Seconds to wait for an element to become visible |
| `--repeat` | `1` | Run the test repeatedly — useful for flaky tests |
| `--repeat-no-init` | | Repeat without re-initialising between runs |
| `--min-success-required` | `100` | Minimum success percentage when using `--repeat` |
| `--test-tv` | | Run the browser non-headless so you can watch at `/test.tv/` |
| `--debug` | | Attach VS Code to `debugpy` using the created profile |
| `--output-json` | | Emit results as JSON |
| `--results-file` | | Path for `results.json` |
| `--keep-token-dir` | | Keep the intermediate run directory |
| `--no-install-further-modules` | | Do not install additional modules for the run |

### Watching a run

`--test-tv` runs the browser in non-headless mode and streams it to `/test.tv/`,
so you can watch the test drive the UI. This is the quickest way to understand
why an assertion fails.

zCICD exposes the same view through its **Test TV** action on a branch.

## Other commands

| Command | Purpose |
| --- | --- |
| `odoo robot list` | List the available robot tests |
| `odoo robot run-all` | Run every robot matching the `robotests` file patterns |
| `odoo robot cleanup` | Clean up after runs |
| `odoo robot make-variable-file` | Generate the `.robot-vars` variables file |
| `odoo robot start-cobot` | Start cobot, reachable at `http://<host>/cobot` |

## Working in VS Code

`odoo robot setup` creates the `~/.robotenv` virtualenv specifically so editor
extensions can find a Robot Framework interpreter — the
[RobotCode](https://marketplace.visualstudio.com/items?itemName=d-biehl.robotcode)
extension picks it up.

Once it is installed:

- The **test tube** icon in the activity bar lists the tests in the project.
- Each test has a **play icon** in the editor gutter to run or re-run it.
- Breakpoints can be set directly in the `.robot` file, and `--debug` attaches
  the debugger.
- A running test can be stopped from the toolbar.

If the interpreter is not detected, point the extension at
`~/.robotenv/bin/python`.

## Running the same tests in CI

zCICD runs these tests as part of a **test run**, alongside unit tests and
migration tests. It applies the same tag filters, and can run the suite at
several parallelism levels to load-test the system.

See the zCICD documentation on test runs for how results are reported and how
zCICD decides which tests to skip.
