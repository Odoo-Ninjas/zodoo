class GlobalCommands:
    # so commands can call other commands
    def __init__(self):
        self.commands = {}

    def register(self, cmd, force_name=None):
        name = force_name or cmd.callback.__name__
        if name in self.commands:
            raise Exception()
        self.commands[name] = cmd

    def invoke(self, ctx, cmd, missing_ok=False, *args, **kwargs):
        if cmd not in self.commands:
            if not missing_ok:
                raise Exception(f"CMD not found: {cmd}")
            else:
                return
        return ctx.invoke(self.commands[cmd], *args, **kwargs)
