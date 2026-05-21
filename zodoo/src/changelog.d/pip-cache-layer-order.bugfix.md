Adding a new pip dependency to a custom module no longer triggers a
full project-image rebuild. Two things changed:

1. **Layer-Reordering** — the project Dockerfile template was
   restructured so that the static `MARKER COMMON_STATIC` block
   (zodoo CLI install, ~48 s of static APT+venv setup) runs **before**
   the volatile project-delta block (`ODOO_PROJECT_REQUIREMENTS` /
   `ODOO_PROJECT_DEB_REQUIREMENTS` ARG consumption + apt/pip install).
   A new project pip dep now only rebuilds the final 3 layers (~15 s)
   instead of all 27 (~130 s).

2. **Naming refactor** — build args renamed to make the framework-vs-
   project split obvious:
   - `ODOO_REQUIREMENTS` → `ODOO_PROJECT_REQUIREMENTS`
   - `ODOO_DEB_REQUIREMENTS` → `ODOO_PROJECT_DEB_REQUIREMENTS`
   - `ODOO_FRAMEWORK_REQUIREMENTS` unchanged (already clear)

   "framework" = Odoo's own upstream requirements.txt (rarely changes,
   baked into the per-version base image). "project" = your custom
   modules + requirements.static (changes constantly, lives in the
   project layer). Container file names follow:
   `/root/project_requirements.txt`,
   `/root/project_deb_requirements.txt`,
   `/root/framework_constraints.txt`.

BREAKING: external tools or CI scripts that set the old `ODOO_REQUIREMENTS`
/ `ODOO_DEB_REQUIREMENTS` build args directly must be updated. Existing
projects must run `odoo reload` once after updating to pick up the new
template.
