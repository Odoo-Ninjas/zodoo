"""Transport for ADDITIONAL_ODOO_CONFIG between host and container.

``~/.odoo/odoo.config`` (and the per-project variant) let a machine set
odoo.conf options without rebuilding the image. The content travels as a
docker-compose environment variable, and an environment variable holds no
newlines - so the lines are joined with a separator on the host
(``__after_compose.py``) and split again in the container
(``odoo/bin/tools.py``).

Both sides import this module, because they drifted apart once already: the
host joined the lines, the container handed the joined single line straight
to ``configparser``, and configparser reads ``[options]___|||___dbfilter =
.*`` as a section header whose remainder is noise. Result: every option was
dropped without a word, and ``~/.odoo/odoo.config`` did nothing at all.
"""

SEPARATOR = "___|||___"


def encode(text):
    """Config file content -> one line, safe for an env variable."""
    return SEPARATOR.join(text.splitlines())


def decode(raw):
    """The env variable -> config file content, as configparser wants it."""
    return "\n".join(raw.split(SEPARATOR))


def carries_options(text):
    """True if `text` holds anything but section headers, blanks and comments.

    Used to tell "the user configured nothing" apart from "the user
    configured something and it got lost" - only the second one deserves a
    warning.
    """
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith(("#", ";")):
            continue
        if line.startswith("[") and line.endswith("]"):
            continue
        return True
    return False
