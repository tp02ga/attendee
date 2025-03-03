import asyncio
import datetime
import json
import os
import threading
import time
from time import sleep

import cv2
import numpy as np
import requests
import undetected_chromedriver as uc
from pyvirtualdisplay import Display
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from websockets.sync.server import serve

from bots.bot_adapter import BotAdapter
from bots.bot_controller.automatic_leave_configuration import AutomaticLeaveConfiguration
from bots.teams_bot_adapter.teams_ui_methods import (
    TeamsUIMethods,
    UiRequestToJoinDeniedException,
    UiRetryableException,
)

from bots.web_bot_adapter import WebBotAdapter

class TeamsBotAdapter(WebBotAdapter, TeamsUIMethods):

    def get_chromedriver_payload_file_name(self):
        return "teams_bot_adapter/teams_chromedriver_payload.js"

    def get_websocket_port(self):
        return 8097