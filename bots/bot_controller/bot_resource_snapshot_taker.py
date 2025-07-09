import datetime
import logging

from django.utils import timezone

from bots.models import Bot, BotResourceSnapshot

logger = logging.getLogger(__name__)


from pathlib import Path


def _detect_cgroup_layout():
    """Return paths to the usage and stat files for this container."""
    # cgroup v2 has /sys/fs/cgroup/cgroup.controllers
    if Path("/sys/fs/cgroup/cgroup.controllers").exists():
        root = Path("/sys/fs/cgroup")  # unified v2 mount
        usage_file = root / "memory.current"  # bytes
        stat_file = root / "memory.stat"
    else:  # cgroup v1
        root = Path("/sys/fs/cgroup")
        usage_file = root / "memory" / "memory.usage_in_bytes"
        stat_file = root / "memory" / "memory.stat"
    return usage_file, stat_file


def _read_first_match(path: Path, key: str, default: int = 0) -> int:
    """Parse `/sys/fs/cgroup/*/memory.stat` and return the integer after *key*."""
    try:
        with path.open() as fh:
            for line in fh:
                if line.startswith(key):
                    return int(line.split()[1])
    except FileNotFoundError:
        pass
    return default


def container_memory_mib() -> int:
    usage_path, stat_path = _detect_cgroup_layout()

    # Raw usage: everything the pod is holding.
    with usage_path.open() as fh:
        usage_bytes = int(fh.read().strip())

    # Reclaimable cache: what metrics-server subtracts.
    inactive_file = _read_first_match(stat_path, "inactive_file")

    working_set = max(usage_bytes - inactive_file, 0)
    return working_set // (1024 * 1024)


class BotResourceSnapshotTaker:
    """
    A class to handle taking snapshots of bot resource usage (CPU, RAM).
    """

    def __init__(self, bot: Bot):
        """
        Initializes the snapshot taker for a specific bot.

        It fetches the last snapshot time from the database once upon creation to
        minimize database queries.
        """
        self.bot = bot
        self._last_snapshot_time = None

    def save_snapshot_if_needed(self):
        if not self.bot.save_resource_snapshots():
            return

        now = timezone.now()

        # Don't take a snapshot if it's been less than 2 minutes since the last snapshot.
        if self._last_snapshot_time:
            if (now - self._last_snapshot_time) < datetime.timedelta(minutes=2):
                return

        try:
            ram_usage_megabytes = container_memory_mib()
        except Exception as e:
            # Could log this error, but for now we will just skip taking the snapshot.
            logger.error(f"Error getting resource usage for bot {self.bot.object_id}: {e}")
            return

        snapshot_data = {
            "ram_usage_megabytes": ram_usage_megabytes,
        }

        BotResourceSnapshot.objects.create(bot=self.bot, data=snapshot_data)

        # Update the last snapshot time in memory for subsequent checks
        self._last_snapshot_time = now
