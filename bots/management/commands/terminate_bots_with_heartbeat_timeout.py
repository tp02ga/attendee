import logging
import os
from typing import List

from django.core.management.base import BaseCommand
from kubernetes import client, config
from django.db import models
from django.utils import timezone
from bots.models import Bot, BotStates, BotEventManager, BotEventTypes, BotEventSubTypes

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Terminates bots that have not sent a heartbeat in the last ten minutes"

    def __init__(self):
        super().__init__()
        # Initialize kubernetes client
        try:
            config.load_incluster_config()
        except config.ConfigException:
            config.load_kube_config()
        self.v1 = client.CoreV1Api()
        self.namespace = "attendee"
        logger.info("initialized kubernetes client")

    def terminate_bot(self, bot):
        try:
            BotEventManager.create_event(
                bot=bot,
                event_type=BotEventTypes.FATAL_ERROR,
                event_sub_type=BotEventSubTypes.FATAL_ERROR_HEARTBEAT_TIMEOUT,
            )
        except Exception as e:
            logger.error(f"Failed to create fatal error heartbeat timeout event for bot {bot.id}: {str(e)}")

        # There isn't really a safe way to terminate the bot if it's running as a celery task
        if not os.getenv("LAUNCH_BOT_METHOD") == "kubernetes":
            return
        
        # Try to delete the pod if it exists
        try:
            pod_name = bot.k8s_pod_name()
            self.v1.delete_namespaced_pod(
                name=pod_name, 
                namespace=self.namespace, 
                grace_period_seconds=0,
            )
            logger.info(f"Deleted pod: {pod_name}")
        except client.ApiException as pod_error:
            # 404 means pod doesn't exist, which is fine
            if pod_error.status != 404:
                logger.warning(f"Error deleting pod {pod_name}: {str(pod_error)}")

    def handle(self, *args, **options):
        logger.info("Terminating bots with heartbeat timeout...")

        try:
            ten_minutes_ago_timestamp = int(timezone.now().timestamp() - 600)

            # Find non-terminal bots where:
            # - last heartbeat is over 10 minutes ago
            problem_bots = Bot.objects.filter(
                ~Bot.get_terminal_states_q_filter() & 
                (
                    (models.Q(last_heartbeat_timestamp__isnull=False) & 
                     models.Q(last_heartbeat_timestamp__lt=ten_minutes_ago_timestamp))
                )
            )
            
            logger.info(f"Found {problem_bots.count()} bots with heartbeat timeout")
            
            # Create fatal error events for each bot
            for bot in problem_bots:
                try:
                    logger.info(f"Terminating bot {bot.object_id} due to heartbeat timeout")
                    self.terminate_bot(bot)

                except Exception as e:
                    logger.error(f"Failed to terminate bot {bot.object_id}: {str(e)}")
                    
            logger.info("Finished terminating bots with heartbeat timeout")

        except client.ApiException as e:
            logger.error(f"Failed to terminate bots with heartbeat timeout: {str(e)}")
