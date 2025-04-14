import time

from bots.google_meet_bot_adapter.google_meet_ui_methods import (
    GoogleMeetUIMethods,
)
from bots.web_bot_adapter import WebBotAdapter


class GoogleMeetBotAdapter(WebBotAdapter, GoogleMeetUIMethods):
    def __init__(
        self,
        *args,
        google_meet_closed_captions_language: str | None,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)
        self.google_meet_closed_captions_language = google_meet_closed_captions_language

    def get_chromedriver_payload_file_name(self):
        return "google_meet_bot_adapter/google_meet_chromedriver_payload.js"

    def get_websocket_port(self):
        return 8765

    def get_first_buffer_timestamp_ms(self):
        if self.media_sending_enable_timestamp_ms is None:
            return None
        # Doing a manual offset for now to correct for the screen recorder delay. This seems to work reliably.
        return self.media_sending_enable_timestamp_ms

    def send_raw_image(self, image_bytes):
        # If we have a memoryview, convert it to bytes
        if isinstance(image_bytes, memoryview):
            image_bytes = image_bytes.tobytes()

        # Pass the raw bytes directly to JavaScript
        # The JavaScript side can convert it to appropriate format
        for i in range(4):
            self.driver.execute_script(
                """
                const bytes = new Uint8Array(arguments[0]);
                window.botOutputManager.displayImage(bytes);
            """,
                list(image_bytes),
            )

            # Sending it several times seems necessary for full reliability.
            time.sleep(0.25)
