import os
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from selenium.common.exceptions import TimeoutException

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

        # Wait for the join audio button to be visible and click it
        join_audio_button = WebDriverWait(self.driver, 60).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "button.join-audio-by-voip__join-btn"))
        )
        # Use JavaScript to click the button to avoid click interception issues
        self.driver.execute_script("arguments[0].click();", join_audio_button)

        # Then find a button with the arial-label "More meeting control " and click it
        more_meeting_control_button = WebDriverWait(self.driver, 60).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "button[aria-label='More meeting control']"))
        )
        self.driver.execute_script("arguments[0].click();", more_meeting_control_button)

        # Then find an <a> tag with the arial label "Captions" and click it
        captions_button = WebDriverWait(self.driver, 60).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "a[aria-label='Captions']"))
        )
        self.driver.execute_script("arguments[0].click();", captions_button)

        # Then find an <a> tag with the arial label "Your caption settings grouping Show Captions" and click it
        your_caption_settings_grouping_show_captions_button = WebDriverWait(self.driver, 60).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "a[aria-label='Your caption settings grouping Show Captions']"))
        )
        self.driver.execute_script("arguments[0].click();", your_caption_settings_grouping_show_captions_button)
        
        # Then see if it created a modal to select the caption language. If so, just click the save button
        try:
            save_button = WebDriverWait(self.driver, 3).until(
                EC.element_to_be_clickable((By.XPATH, "//button[contains(@class, 'zm-btn--primary') and contains(text(), 'Save')]"))
            )
            self.driver.execute_script("arguments[0].click();", save_button)
        except TimeoutException:
            # No modal appeared or Save button not found within 3 seconds, continue
            pass

        self.ready_to_show_bot_image()

    def click_leave_button(self):
        self.driver.execute_script("leaveMeeting()")
