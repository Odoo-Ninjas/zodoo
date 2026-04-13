def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "bake: end-to-end test for the `odoo bake` flow; requires Docker, "
        "gimera and network access (clones full Odoo). Heavy — opt in with "
        "`pytest -m bake`.",
    )
