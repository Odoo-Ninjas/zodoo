"""The rsync tool image must be built but never started.

Background: rsync/docker-compose.yml declared no profile, so lib_composer's
`setdefault("profiles", ["auto"])` put it in the profile that `odoo up -d`
starts. Its entrypoint is `rsync` with no arguments, so the container prints
its usage and exits 1 -- and since 7.2.0 restart_unhealthy_containers.sh
counts anything outside 0|130|143 as a crash and restarts it every minute on
DEVMODE=0 hosts. DEVMODE=1 skips the watchdog entirely, which is why nobody
noticed.

The obvious fix -- move it to the existing "manual" profile -- would have
stopped it being built, because `odoo build` runs with profile "auto", and a
missing <project>-rsync:latest surfaces only when someone restores a
snapshot.
"""

from pathlib import Path

import yaml

from zodoo import consts

REPO_ROOT = Path(__file__).resolve().parents[4]


class TestProfileConstants:
    def test_build_only_is_not_a_startable_profile(self):
        """The trap this whole design avoids.

        up() defaults to profile="all" and iterates resolve_profiles(), i.e.
        DOCKER_PROFILES. Listing build_only there would start the tool
        container again through the back door -- the exact bug being fixed.
        """
        assert consts.BUILD_ONLY_PROFILE not in consts.DOCKER_PROFILES

    def test_resolve_all_does_not_pull_in_build_only(self):
        assert consts.BUILD_ONLY_PROFILE not in consts.resolve_profiles("all")

    def test_build_covers_running_services_and_tool_images(self):
        assert "auto" in consts.BUILD_PROFILES
        assert consts.BUILD_ONLY_PROFILE in consts.BUILD_PROFILES


class TestRsyncService:
    @staticmethod
    def _service():
        path = REPO_ROOT / "rsync" / "docker-compose.yml"
        return yaml.safe_load(path.read_text())["services"]["rsync"]

    def test_is_build_only(self):
        assert self._service().get("profiles") == [
            consts.BUILD_ONLY_PROFILE
        ], "rsync must not sit in a profile that `odoo up -d` starts"

    def test_is_not_started_by_up(self):
        for profile in consts.DOCKER_PROFILES:
            assert profile not in (self._service().get("profiles") or [])

    def test_still_declares_a_build(self):
        """Without this the image is gone and snapshots break silently."""
        assert self._service().get("build")


class TestBuildUsesBuildProfiles:
    """`odoo build` has to pass the tool profile, otherwise compose skips it.

    Checked at source level because the two call sites sit inside a closure
    that needs a full config and a docker daemon to invoke.
    """

    @staticmethod
    def _source():
        return (
            REPO_ROOT
            / "zodoo"
            / "src"
            / "zodoo"
            / "lib_control_with_docker.py"
        ).read_text()

    def test_no_build_path_is_left_on_auto_only(self):
        assert '__get_cmd(config, profile="auto")' not in self._source(), (
            "a build path still renders only the auto profile -- the tool "
            "images would not be built"
        )

    def test_both_build_paths_pass_build_profiles(self):
        """One path for buildx bake, one for plain `docker compose build`."""
        assert (
            self._source().count("__get_cmd(config, profile=BUILD_PROFILES)")
            == 2
        )
