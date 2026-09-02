# used to read and write to settings
import os
import stat
from pathlib import Path
from .tools import atomic_write


def _get_ignore_case_item(d, k):
    try:
        return d[k]
    except KeyError:
        if isinstance(k, str):
            for i in d.keys():
                if i.lower() == k.lower():
                    return d[i]
            else:
                raise
        else:
            raise


class MyConfigParser:
    def __init__(self, fileName, debug=False):
        if isinstance(fileName, dict):
            self.fileName = None
            self.configOptions = fileName
        else:
            self.fileName = Path(fileName)
            self.configOptions = {}
            if self.fileName.exists():
                self._open()
        del fileName
        self.debug = debug
        self.remove_keys = set()

    def apply(self, other):
        for k in other.keys():
            self[k] = other[k]
            if k in self.remove_keys:
                self.remove_keys.remove(k)

    def clear(self):
        self.configOptions.clear()
        if self.fileName:
            self.fileName.parent.mkdir(exist_ok=True, parents=True)
            self.fileName.write_text("")
        self.remove_keys.clear()

    def keys(self):
        return self.configOptions.keys() - self.remove_keys

    def _open(self):
        if not self.fileName or not self.fileName.exists():
            return
        content = self.fileName.read_text().strip()
        for line in content.split("\n"):
            # If it isn't a comment get the variable and value and put it on a dict
            if not line.startswith("#") and len(line) > 1:
                if "=" not in line:
                    import click

                    click.secho(
                        f"Invalid configuration option '{line}' ignored.",
                        fg="red",
                    )
                    continue
                key, val = line.rstrip("\n").split("=", 1)
                val = val.strip()
                val = val.strip('"')
                val = val.strip("'")
                self.configOptions[key.strip()] = val

    def write(self):
        handled_keys = set()
        if not self.fileName:
            return
        # Write the file contents
        if not self.fileName.is_file():
            self.fileName.parent.mkdir(exist_ok=True, parents=True)

        lines = []
        if self.fileName.exists():
            lines = self.fileName.read_text().splitlines()

        def format_line(key, val):
            if val is None:
                raise Exception(f"None value not allowed for: {key}")
            return key + "=" + str(val)

        # Loop through the file to change with new values in dict
        def _update_lines():
            for line in lines:
                if line.startswith("#") or len(line) <= 1:
                    yield line
                    continue
                key, val = line.rstrip("\n").split("=", 1)
                key = key.strip()
                if key in self.remove_keys:
                    self.remove_keys.remove(key)
                    if key in self.configOptions.keys():
                        self.configOptions.pop(key, None)
                    continue
                if key in self.configOptions:
                    newVal = self.configOptions[key]

                    # Only update if the variable value has changed
                    line = format_line(key, newVal)
                yield line
                handled_keys.add(key)

            for key in self.configOptions.keys():
                if key not in handled_keys:
                    yield format_line(key, self.configOptions[key])

        # Set the permissions BEFORE the rename: atomic_write creates a new
        # file and replaces the old one, so the previous file's permissions are
        # gone afterwards. Whoever chmods only after the fact leaves the file
        # sitting there with the umask's permissions for a moment - and with a
        # secret in it, that moment is the problem.
        prev_mode = None
        try:
            prev_mode = stat.S_IMODE(Path(self.fileName).stat().st_mode)
        except OSError:
            pass

        with atomic_write(self.fileName) as file:
            file.write_text("\n".join(_update_lines()) + "\n")
            if prev_mode is not None:
                # Preserve the existing permissions - without this, every
                # write would reset them to the umask.
                file.chmod(prev_mode)
            if self._holds_secret():
                self._tighten(file)

    # Settings whose file nobody but the owner should be able to read.
    # OFFSITE_PASSPHRASE is the most expensive of them: it decrypts the
    # project's entire offsite backup.
    SECRET_KEY_HINTS = (
        "PASSPHRASE",
        "PASSWORD",
        "SECRET",
        "TOKEN",
        "PRIVATE_KEY",
        # PGBR_CIPHER_PASS heisst weder ...PASSPHRASE noch ...PASSWORD und
        # fiel deshalb durch dieses Raster - ausgerechnet die Passphrase, die
        # dieser Kommentar oben als die teuerste nennt. Auf einer produktiven
        # Instanz lag die Datei damit weiter auf 0664.
        #
        # Absichtlich "CIPHER" und nicht "CIPHER_PASS": das trifft auch
        # PGBR_CIPHER_TYPE, was kein Geheimnis ist. Eine Datei zu eng zu
        # ziehen kostet nichts, eine zu weit gelassene kostet alles.
        "CIPHER",
    )

    def _holds_secret(self):
        return any(
            hint in key.upper()
            for key in self.configOptions
            for hint in self.SECRET_KEY_HINTS
        )

    def _tighten(self, path):
        """Take every permission away from others (0600) when a secret is in it.

        Until now settings files landed on the umask's default (often 0644) and
        were protected only by the permissions of the home directory. If a home
        is ever created as 0755 - entirely possible on a machine with many
        instance users - the backup passphrase lies open.

        Only what sits below the own home is touched: /etc/odoo/settings is
        system-wide and has to stay readable for everyone, otherwise no other
        instance finds its base settings any more.
        """
        try:
            home = Path.home().resolve()
            try:
                Path(self.fileName).resolve().parent.relative_to(home)
            except ValueError:
                return
            mode = stat.S_IMODE(path.stat().st_mode)
            if mode & 0o077:
                path.chmod(mode & ~0o077)
        except OSError:
            # Permissions are an extra, not a reason to fail the write - the
            # value is already in the file at this point.
            pass

    def __getitem__(self, key):
        for data in (self.configOptions, os.environ):
            if key in self.remove_keys and data == self.configOptions:
                continue
            try:
                if isinstance(key, int):
                    actual_key = list(data.keys())[key]
                    return _get_ignore_case_item(data, actual_key)
                return _get_ignore_case_item(data, key)
            except (KeyError, IndexError):
                continue
        raise KeyError(f"Key {key} doesn't exist in {self.fileName}")

    def __contains__(self, key):
        if not isinstance(key, str):
            return False
        lower = key.lower()
        for data in (self.configOptions, os.environ):
            if data is self.configOptions and key in self.remove_keys:
                continue
            for k in data.keys():
                if k.lower() == lower:
                    return True
        return False

    def __iter__(self):
        for k in self.configOptions.keys():
            if k in self.remove_keys:
                continue
            yield k

    def __setitem__(self, key, value):
        if key in self.remove_keys:
            self.remove_keys.remove(key)
        if isinstance(value, list):
            value_list = "("
            for item in value:
                value_list += ' "' + item + '"'
            value_list += " )"
            self.configOptions[key] = value_list
        else:
            self.configOptions[key] = value

    def get(self, key, default_value=""):
        try:
            return self[key]
        except Exception:
            return default_value

    def pop(self, key, default=None):
        self.remove_keys.add(key)
        return self.configOptions.pop(key, default)
