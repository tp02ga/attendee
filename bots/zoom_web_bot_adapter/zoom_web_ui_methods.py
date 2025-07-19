import os
import time
import logging
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from selenium.common.exceptions import TimeoutException
from bots.web_bot_adapter.ui_methods import UiCouldNotClickElementException, UiCouldNotJoinMeetingWaitingForHostException, UiCouldNotJoinMeetingWaitingRoomTimeoutException, UiCouldNotLocateElementException, UiLoginRequiredException, UiMeetingNotFoundException, UiRequestToJoinDeniedException, UiRetryableExpectedException

logger = logging.getLogger(__name__)

class ZoomWebUIMethods:
    def __init__(self, driver):
        self.driver = driver

    def attempt_to_join_meeting(self):
        # Get the directory of the current file and construct path to HTML file
        current_dir = os.path.dirname(os.path.abspath(__file__))
        html_file_path = os.path.join(current_dir, 'zoom_web_chromedriver_page.html')
        file_url = f'file://{html_file_path}'
        
        self.driver.get(file_url)

        self.driver.execute_cdp_cmd(
            "Browser.grantPermissions",
            {
                "origin": file_url,
                "permissions": [
                    "geolocation",
                    "audioCapture",
                    "displayCapture",
                    "videoCapture",
                ],
            },
        )

        # Call the joinMeeting function
        self.driver.execute_script("joinMeeting()")

        # Click the join audio button. If we're in the waiting room, we'll get a different experience and won't need to do this.
        self.click_join_audio_button()

        # Then find a button with the arial-label "More meeting control " and click it
        logger.info("Waiting for more meeting control button")
        more_meeting_control_button = WebDriverWait(self.driver, 60).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "button[aria-label='More meeting control']"))
        )
        logger.info("More meeting control button found, clicking")
        self.driver.execute_script("arguments[0].click();", more_meeting_control_button)


        # Then find an <a> tag with the arial label "Captions" and click it
        logger.info("Waiting for captions button")
        captions_button = WebDriverWait(self.driver, 60).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "a[aria-label='Captions']"))
        )
        logger.info("Captions button found, clicking")
        self.driver.execute_script("arguments[0].click();", captions_button)

        # Then find an <a> tag with the arial label "Your caption settings grouping Show Captions" and click it
        logger.info("Waiting for your caption settings grouping Show Captions button")
        your_caption_settings_grouping_show_captions_button = WebDriverWait(self.driver, 60).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "a[aria-label='Your caption settings grouping Show Captions']"))
        )
        logger.info("Your caption settings grouping Show Captions button found, clicking")
        self.driver.execute_script("arguments[0].click();", your_caption_settings_grouping_show_captions_button)
        
        # Then see if it created a modal to select the caption language. If so, just click the save button
        try:
            logger.info("Waiting for save button")
            save_button = WebDriverWait(self.driver, 2).until(
                EC.element_to_be_clickable((By.XPATH, "//button[contains(@class, 'zm-btn--primary') and contains(text(), 'Save')]"))
            )
            logger.info("Save button found, clicking")
            self.driver.execute_script("arguments[0].click();", save_button)
        except TimeoutException:
            # No modal appeared or Save button not found within 2 seconds, continue
            logger.info("No modal appeared or Save button not found within 2 seconds, continuing")

        # Then see if it created a modal to confirm that the meeting is being transcribed.
        try:
            logger.info("Waiting for OK button")
            ok_button = WebDriverWait(self.driver, 2).until(
                EC.element_to_be_clickable((By.XPATH, "//button[contains(@class, 'zm-btn--primary') and contains(text(), 'OK')]"))
            )
            logger.info("OK button found, clicking")
            self.driver.execute_script("arguments[0].click();", ok_button)
        except TimeoutException:
            # No modal appeared or OK button not found within 2 seconds, continue
            logger.info("No modal appeared or OK button not found within 2 seconds, continuing")

        self.ready_to_show_bot_image()

    def click_leave_button(self):
        self.driver.execute_script("leaveMeeting()")

    def check_if_waiting_room_timeout_exceeded(self, waiting_room_timeout_started_at, step):
        waiting_room_timeout_exceeded = time.time() - waiting_room_timeout_started_at > self.automatic_leave_configuration.waiting_room_timeout_seconds
        if waiting_room_timeout_exceeded:
            # If there is more than one participant in the meeting, then the bot was just let in and we should not timeout
            if len(self.participants_info) > 1:
                logger.info("Waiting room timeout exceeded, but there is more than one participant in the meeting. Not aborting join attempt.")
                return
            self.abort_join_attempt()
            logger.info("Waiting room timeout exceeded. Raising UiCouldNotJoinMeetingWaitingRoomTimeoutException")
            raise UiCouldNotJoinMeetingWaitingRoomTimeoutException("Waiting room timeout exceeded", step)

    def click_join_audio_button(self):
        num_attempts_to_look_for_join_audio_button = self.automatic_leave_configuration.waiting_room_timeout_seconds * 10
        logger.info("Waiting for join audio button...")
        waiting_room_timeout_started_at = time.time()
        
        for attempt_index in range(num_attempts_to_look_for_join_audio_button):
            try:
                join_audio_button = WebDriverWait(self.driver, 1).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, "button.join-audio-by-voip__join-btn"))
                )
                logger.info("Join audio button found")
                self.driver.execute_script("arguments[0].click();", join_audio_button)
                return
            except TimeoutException as e:
                self.check_if_waiting_room_timeout_exceeded(waiting_room_timeout_started_at, "click_join_audio_button")

                last_check_timed_out = attempt_index == num_attempts_to_look_for_join_audio_button - 1
                if last_check_timed_out:
                    logger.info("Could not find join audio button. Timed out. Raising UiCouldNotLocateElementException")
                    raise UiCouldNotLocateElementException(
                        "Could not find join audio button. Timed out.",
                        "click_join_audio_button",
                        e,
                    )
            except Exception as e:
                logger.info(f"Could not find join audio button. Unknown error {e} of type {type(e)}. Raising UiCouldNotLocateElementException")
                raise UiCouldNotLocateElementException(
                    "Could not find join audio button. Unknown error.",
                    "click_join_audio_button",
                    e,
                )
