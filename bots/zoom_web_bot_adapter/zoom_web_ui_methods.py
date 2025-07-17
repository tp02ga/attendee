import os
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

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

        self.ready_to_show_bot_image()

    def click_leave_button(self):
        self.driver.execute_script("leaveMeeting()")
