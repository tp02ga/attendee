import logging

from selenium.webdriver.common.keys import Keys

from bots.web_bot_adapter import WebBotAdapter
from bots.zoom_web_bot_adapter.zoom_web_ui_methods import ZoomWebUIMethods

logger = logging.getLogger(__name__)


class ZoomWebBotAdapter(WebBotAdapter, ZoomWebUIMethods):
    def __init__(
        self,
        *args,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)

    def get_chromedriver_payload_file_name(self):
        return "zoom_web_bot_adapter/zoom_web_chromedriver_payload.js"

    def get_websocket_port(self):
        return 8765

    def is_sent_video_still_playing(self):
        return False

    def send_video(self, video_url):
        logger.info(f"send_video called with video_url = {video_url}. This is not supported for zoom web")
        return

    def send_chat_message(self, text):
        logger.info(f"send_chat_message called with text = {text}. This is not supported for zoom web")
        return

    def get_staged_bot_join_delay_seconds(self):
        return 5
