import logging

from celery import shared_task
from kubernetes import client, config

from bots.models import Bot, BotEventManager, BotEventTypes

logger = logging.getLogger(__name__)
from bots.bot_pod_creator import BotPodCreator


@shared_task(bind=True, soft_time_limit=3600)
def restart_bot_pod(self, bot_id):
    """
    Restart a bot pod.
    """

    logger.info(f"Restarting bot pod for bot {bot_id}")

    bot = Bot.objects.get(id=bot_id)

    # Initialize kubernetes client
    try:
        config.load_incluster_config()
    except config.ConfigException:
        config.load_kube_config()
    v1 = client.CoreV1Api()
    namespace = "attendee"

    # Check if pod already exists with this name
    pod_name = bot.k8s_pod_name()
    try:
        # Directly read the specific pod by name instead of listing all pods
        existing_pod = v1.read_namespaced_pod(name=pod_name, namespace=namespace)

        # Delete the pod if it exists (we'll only get here if the pod exists)
        logger.info(f"Found existing pod {pod_name}, deleting it before creating a new one")
        v1.delete_namespaced_pod(name=pod_name, namespace=namespace, grace_period_seconds=60)

        # Sleep until the pod is no longer found
        num_retries = 20
        for i in range(num_retries):
            try:
                v1.read_namespaced_pod(name=pod_name, namespace=namespace)
            except client.ApiException as e:
                if e.status == 404:
                    logger.info(f"Pod {pod_name} deleted successfully")
                    break
                else:
                    logger.error(f"Error checking for existing pod: {str(e)}")
            if i == num_retries - 1:
                logger.error(f"Pod {pod_name} did not delete after {num_retries} retries")
                raise Exception(f"Pod {pod_name} did not delete after {num_retries} retries")
            time.sleep(5)

    except client.ApiException as e:
        if e.status == 404:
            # Pod doesn't exist - this is fine, just continue
            logger.info(f"Pod {pod_name} not found, no need to delete")
        else:
            # Some other API error occurred
            logger.error(f"Error checking for existing pod: {str(e)}")

    BotEventManager.create_event(bot, BotEventTypes.NEW_POD_CREATED)
    BotEventManager.create_event(bot, BotEventTypes.JOIN_REQUESTED)
    bot.set_heartbeat()

    bot_pod_creator = BotPodCreator()
    bot_pod_create_result = bot_pod_creator.create_bot_pod(bot_id=bot.id, bot_name=bot.k8s_pod_name())

    logger.info(f"Bot pod create result: {bot_pod_create_result}")
