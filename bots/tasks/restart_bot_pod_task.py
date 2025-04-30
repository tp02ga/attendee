import logging

import requests
from celery import shared_task
from django.utils import timezone

from bots.models import Bot, BotEventTypes, BotEventManager
from bots.webhook_utils import sign_payload

logger = logging.getLogger(__name__)
from bots.bot_pod_creator import BotPodCreator


@shared_task(bind=True, soft_time_limit=3600)
def restart_bot_pod(self, bot_id):
    """
    Restart a bot pod.
    """

    logger.info(f"Restarting bot pod for bot {bot_id}")

    bot = Bot.objects.get(id=bot_id)

    BotEventManager.create_event(bot, BotEventTypes.NEW_POD_CREATED)
    BotEventManager.create_event(bot, BotEventTypes.JOIN_REQUESTED)

    bot_pod_creator = BotPodCreator()
    bot_pod_create_result = bot_pod_creator.create_bot_pod(bot_id=bot.id, bot_name=bot.k8s_pod_name())

    logger.info(f"Bot pod create result: {bot_pod_create_result}")