from . import click

if click:

    class AliasedGroup(click.Group):
        """
        Uses startswith to match command
        """

        def list_commands(self, ctx):
            top_level = super().list_commands(ctx)
            nested = []
            for name in top_level:
                cmd = click.Group.get_command(self, ctx, name)
                if type(cmd) == type(self):
                    nested.extend(cmd.list_commands(ctx))
            # deduplicate, preserve top-level order first
            seen = set(top_level)
            extra = [n for n in nested if n not in seen]
            return top_level + extra

        def get_command(self, ctx, cmd_name):
            rv = click.Group.get_command(self, ctx, cmd_name)
            if rv is not None:
                return rv

            all_names = self.list_commands(ctx)

            # top-level prefix matches — only load commands whose name matches
            matches = []
            for n in all_names:
                if n.startswith(cmd_name):
                    resolved = click.Group.get_command(self, ctx, n)
                    if resolved is not None:
                        matches.append((resolved, n))

            # search recursively in subgroups
            for _cmd_name in all_names:
                cmd = click.Group.get_command(self, ctx, _cmd_name)
                if type(cmd) == type(self):
                    matches += [
                        (cmd.get_command(ctx, c), _cmd_name)
                        for c in cmd.list_commands(ctx)
                        if c.startswith(cmd_name)
                    ]

            if len(matches) > 1:
                # try to reduce to exact match
                try_matches = [m for m in matches if m[0].name == cmd_name]
                if len(try_matches) > 1:
                    # same exact name in multiple subgroups (e.g.
                    # composer/reload vs router/reload) — break the tie by
                    # registration order so `odoo reload` keeps resolving to
                    # composer/reload as before
                    matches = try_matches[:1]
                elif try_matches:
                    matches = try_matches

            if len(matches) == 1:
                return matches[0][0]
            elif len(matches) > 1:
                click.echo(
                    "Not unique command: {}\n\n".format(
                        "\n\t".join(x[1] + "/" + x[0].name for x in matches)
                    )
                )
            return None
