import json
import logging
import time
from queue import Empty, SimpleQueue
from threading import Thread
from typing import Callable

from websockets import ConnectionClosed
from websockets.sync.client import connect

logger = logging.getLogger(__name__)


class BotWebsocketClient:
    """
    A websocket loop that sends and receives messages to/from a websocket server
    Designed to be used by a BotController to control the bot audio/video
    remotely.
    """

    # Connection-state values
    NOT_STARTED = "NOT_STARTED"
    CONNECTING = "CONNECTING"
    CONNECTED = "CONNECTED"
    FAILED = "FAILED"
    STOPPED = "STOPPED"

    def __init__(self, url: str, on_message_callback: Callable[[dict], None]):
        self.on_message_callback = on_message_callback
        self.websocket_url = url
        self.websocket = None

        self.connection_state = self.NOT_STARTED
        self.connection_thread = None
        self.recv_loop_thread = None
        self.send_loop_thread = None
        self.send_queue = SimpleQueue()

        self._max_retries = 30
        self._retry_delay_s = 2
        self.dropped_message_ticker = 0

    # --------------------------------------------------------------------- #
    #  Public helpers                                                       #
    # --------------------------------------------------------------------- #

    def started(self):
        return self.connection_state != self.NOT_STARTED

    def start(self):
        logger.info(f"Starting BotWebsocketClient for url {self.websocket_url}")
        self._start_connection_thread()

    def stop(self):
        logger.info("Stopping BotWebsocketClient")
        try:
            if self.websocket:
                self.websocket.close()
        except Exception as e:
            logger.error("Error closing BotWebsocketClient websocket: %s", e)
        finally:
            self.connection_state = self.STOPPED

    def send_async(self, message: dict):
        if self.connection_state == self.CONNECTED:
            self.send_queue.put(message)
        else:
            if self.dropped_message_ticker % 500 == 0:
                logger.warning("BotWebsocketClient is not connected, it is in state %s, dropping message", self.connection_state)
            self.dropped_message_ticker += 1
    # --------------------------------------------------------------------- #
    #  Internal helpers                                                     #
    # --------------------------------------------------------------------- #
    def _start_connection_thread(self):
        if self.connection_thread and self.connection_thread.is_alive():
            logger.info("Connection thread already running")
            return
        self.connection_thread = Thread(
            target=self._connection_loop, daemon=True
        )
        self.connection_thread.start()

    def _connection_loop(self):
        retries = 0
        self.connection_state = self.CONNECTING
        while self.connection_state == self.CONNECTING and retries < self._max_retries:
            try:
                self.websocket = connect(self.websocket_url)

                logger.info("Websocket connected, waiting for worker threads to finish")

                # if the worker threads are running, wait for them to finish
                if self.recv_loop_thread and self.recv_loop_thread.is_alive():
                    self.recv_loop_thread.join()
                if self.send_loop_thread and self.send_loop_thread.is_alive():
                    self.send_loop_thread.join()

                self.connection_state = self.CONNECTED
                logger.info("Websocket connected, launching worker threads")

                # Launch worker threads (fresh each time we reconnect)
                self.recv_loop_thread = Thread(target=self.recv_loop, daemon=True)
                self.send_loop_thread = Thread(target=self.send_loop, daemon=True)
                self.recv_loop_thread.start()
                self.send_loop_thread.start()
                return  # success – leave the loop
            except Exception as e:
                retries += 1
                logger.warning(
                    "Connect attempt %d/%d failed: %s",
                    retries,
                    self._max_retries,
                    e,
                )
                time.sleep(self._retry_delay_s)

        # Handle case where we were stopped before we could connect
        if self.connection_state != self.CONNECTING:
            logger.info("Connection loop exited because connection state is %s", self.connection_state)
            return

        # Exhausted retries
        self.connection_state = self.FAILED
        logger.error("Failed to establish websocket connection after %d retries", self._max_retries)

    def _trigger_reconnect(self):
        if self.connection_state in [self.CONNECTING, self.FAILED, self.STOPPED]:
            logger.info("Aborting websocket reconnect because connection state is %s", self.connection_state)
            return  # already trying or permanently failed
        logger.info("Triggering websocket reconnect")
        self._start_connection_thread()

    # --------------------------------------------------------------------- #
    #  Worker threads                                                       #
    # --------------------------------------------------------------------- #
    def send_loop(self):
        logger.info("BotWebsocketClient send loop started")
        while self.connection_state == self.CONNECTED:
            try:
                message = self.send_queue.get(timeout=1)
            except Empty:
                continue  # nothing queued yet

            try:
                self.websocket.send(json.dumps(message))
            except OSError as e:
                logger.info("Send failed (%s). Leaving loop.", e)
                break

        logger.info("BotWebsocketClient send loop exited")
        self._trigger_reconnect()

    def recv_loop(self):
        logger.info("BotWebsocketClient recv loop started")
        while self.connection_state == self.CONNECTED:
            try:
                message = self.websocket.recv()
                self.on_message_callback(message)
            except ConnectionClosed:
                logger.info("Connection closed. Leaving loop.")
                break

        logger.info("BotWebsocketClient recv loop exited")
        self._trigger_reconnect()
