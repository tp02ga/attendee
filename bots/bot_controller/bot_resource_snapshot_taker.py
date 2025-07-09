import datetime
import psutil
import logging

from django.utils import timezone

from bots.models import Bot, BotResourceSnapshot

logger = logging.getLogger(__name__)


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
            process = psutil.Process()
            # Get CPU usage. The first call is blocking with an interval.
            cpu_usage_percent = process.cpu_percent(interval=0.1)
            # Get RAM usage (Resident Set Size)
            ram_usage_bytes = process.memory_info().rss
        except Exception as e:
            # Could log this error, but for now we will just skip taking the snapshot.
            logger.error(f"Error getting resource usage for bot {self.bot.object_id}: {e}")
            return

        snapshot_data = {
            "cpu_usage_percent": cpu_usage_percent,
            "ram_usage_bytes": ram_usage_bytes,
        }

        BotResourceSnapshot.objects.create(bot=self.bot, data=snapshot_data)

        # Update the last snapshot time in memory for subsequent checks
        self._last_snapshot_time = now
