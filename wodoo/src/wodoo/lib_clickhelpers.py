from . import click

if click:

    class AliasedGroup(click.Group):
        """
        Uses startswith to match command. Lazy-loads commands only when matched.
        """

        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self._commands_cache = None

        def _get_all_commands(self, ctx):
            if self._commands_cache is None:
                self._commands_cache = self.list_commands(ctx)
            return self._commands_cache

        def get_command(self, ctx, cmd_name):
            # 1. Exact match – fastest path
            rv = click.Group.get_command(self, ctx, cmd_name)
            if rv is not None:
                return rv

            all_commands = self._get_all_commands(ctx)

            # 2. Prefix-match on top-level names only (no get_command yet)
            matched_names = [n for n in all_commands if n.startswith(cmd_name)]

            # 3. Prefer exact over ambiguous prefix matches
            if len(matched_names) >= 1:
                exact = [n for n in matched_names if n == cmd_name]
                if exact:
                    matched_names = exact
                else:
                    matched_names = []

            # 4. Unique top-level match → return without searching subgroups
            if len(matched_names) == 1:
                return click.Group.get_command(self, ctx, matched_names[0])

            # 5. No top-level match → search subgroups lazily
            sub_matches = []
            if not matched_names:
                for name in all_commands:
                    cmd = click.Group.get_command(self, ctx, name)
                    if isinstance(cmd, type(self)):
                        for sub_name in cmd.list_commands(ctx):
                            if sub_name.startswith(cmd_name):
                                sub_matches.append((name, sub_name, cmd))

                # Prefer exact match among subgroup matches
                if len(sub_matches) > 1:
                    exact = [
                        (p, s, c) for p, s, c in sub_matches if s == cmd_name
                    ]
                    if exact:
                        sub_matches = exact

            if len(sub_matches) == 1:
                _, sub_name, parent_cmd = sub_matches[0]
                return parent_cmd.get_command(ctx, sub_name)

            # 6. Ambiguous → show all candidates
            all_matches = [(None, n) for n in matched_names] + [
                (p, s) for p, s, _ in sub_matches
            ]
            if all_matches:
                click.echo(
                    "Not unique command: {}\n\n".format(
                        "\n\t".join(
                            (p + "/" if p else "") + s for p, s in all_matches
                        )
                    )
                )
            return None

        def shell_complete(self, ctx, incomplete):
            from click.shell_completion import CompletionItem

            results = []

            # Top-level commands matching prefix
            for name in self.list_commands(ctx):
                if name.startswith(incomplete):
                    cmd = click.Group.get_command(self, ctx, name)
                    if cmd is not None:
                        results.append(
                            CompletionItem(name, help=cmd.get_short_help_str())
                        )

            # No top-level matches → flatten subgroup commands
            if not results:
                for name in self.list_commands(ctx):
                    cmd = click.Group.get_command(self, ctx, name)
                    if isinstance(cmd, type(self)):
                        for sub_name in cmd.list_commands(ctx):
                            if sub_name.startswith(incomplete):
                                sub_cmd = cmd.get_command(ctx, sub_name)
                                if sub_cmd is not None:
                                    results.append(
                                        CompletionItem(
                                            sub_name,
                                            help=sub_cmd.get_short_help_str(),
                                        )
                                    )

            return results
