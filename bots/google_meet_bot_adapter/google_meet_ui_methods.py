from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from selenium.common.exceptions import TimeoutException, NoSuchElementException, WebDriverException

class UiException(Exception):
    pass

class UiRetryableException(UiException):
    pass

class UiFatalException(UiException):
    pass

class GoogleMeetUIMethods:
    def locate_element(self, step, condition, wait_time_seconds=60):
        try:
            element = WebDriverWait(self.driver, wait_time_seconds).until(
                condition
            )
            return element
        except Exception as e:
            # Take screenshot when any exception occurs
            self.send_debug_screenshot_message(step, e)
            raise UiFatalException(f"Exception happened when trying to find element for {step}: {e.__class__.__name__}")

    def find_element_by_selector(self, selector_type, selector):
        try:
            return self.driver.find_element(selector_type, selector)
        except NoSuchElementException as e:
            return None

    def look_for_blocked_element(self):
        cannot_join_element = self.find_element_by_selector(By.XPATH, '//*[contains(text(), "You can\'t join this video call")]')
        if cannot_join_element:
            # This means google is blocking us for whatever reason, but we can retry
            raise UiRetryableException("You can't join this video call")

    def look_for_denied_your_request_element(self):
        denied_your_request_element = self.find_element_by_selector(By.XPATH, '//*[contains(text(), "Someone in the call denied your request to join")]')
        if denied_your_request_element:
            self.send_request_to_join_denied_message()
            raise UiFatalException("Someone in the call denied your request to join")

    def fill_out_name_input(self):
        num_attempts_to_look_for_name_input = 30
        print("Waiting for the name input field...")
        for attempt_to_look_for_name_input_index in range(num_attempts_to_look_for_name_input):
            try:
                name_input = WebDriverWait(self.driver, 1).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, 'input[type="text"][aria-label="Your name"]'))
                )
                print("name input found")
                name_input.send_keys(self.display_name)
                return
            except TimeoutException as e:
                self.look_for_blocked_element()

                last_check_timed_out = attempt_to_look_for_name_input_index == num_attempts_to_look_for_name_input - 1
                if last_check_timed_out:
                    self.send_debug_screenshot_message("name_input", e)
                    raise UiFatalException("Could not find name input. Timed out.")

            except Exception as e:
                self.send_debug_screenshot_message("name_input", e)
                raise UiFatalException("Could not find name input. Unknown error.")

    def click_captions_button(self):
        num_attempts_to_look_for_captions_button = 120
        print("Waiting for captions button...")
        for attempt_to_look_for_captions_button_index in range(num_attempts_to_look_for_captions_button):
            try:
                captions_button = WebDriverWait(self.driver, 1).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, 'button[aria-label="Turn on captions"]'))
                )
                print("Captions button found")
                captions_button.click()
                return
            except TimeoutException as e:
                self.look_for_blocked_element()
                self.look_for_denied_your_request_element()

                last_check_timed_out = attempt_to_look_for_captions_button_index == num_attempts_to_look_for_captions_button - 1
                if last_check_timed_out:
                    self.send_debug_screenshot_message("captions_button", e)
                    raise UiFatalException("Could not find captions button. Timed out.")

            except Exception as e:
                self.send_debug_screenshot_message("captions_button", e)
                raise UiFatalException("Could not find captions button. Unknown error.")

   # returns nothing if succeeded, raises an exception if failed
    def attempt_to_join_meeting(self):
        self.driver.get(self.meeting_url)

        self.driver.execute_cdp_cmd(
            "Browser.grantPermissions",
            {
                "origin": self.meeting_url,
                "permissions": [
                    "geolocation",
                    "audioCapture",
                    "displayCapture",
                    "videoCapture",
                    "videoCapturePanTiltZoom",
                ],
            },
        )

        try:
            self.fill_out_name_input()

            print("Waiting for the 'Ask to join' button...")
            join_button = self.locate_element(
                step="join_button",
                condition=EC.presence_of_element_located((By.XPATH, '//button[.//span[text()="Ask to join"]]')),
                wait_time_seconds=60
            )
            print("Clicking the 'Ask to join' button...")
            join_button.click()

            self.click_captions_button()

            print("Waiting for the more options button...")
            MORE_OPTIONS_BUTTON_SELECTOR = 'button[jsname="NakZHc"][aria-label="More options"]'
            more_options_button = self.locate_element(
                step="more_options_button",
                condition=EC.presence_of_element_located((By.CSS_SELECTOR, MORE_OPTIONS_BUTTON_SELECTOR)),
                wait_time_seconds=6
            )
            print("Clicking the more options button...")
            more_options_button.click()

            print("Waiting for the 'Change layout' list item...")
            change_layout_list_item = self.locate_element(
                step="change_layout_item",
                condition=EC.presence_of_element_located((By.XPATH, '//li[.//span[text()="Change layout"]]')),
                wait_time_seconds=6
            )
            print("Clicking the 'Change layout' list item...")
            change_layout_list_item.click()

            print("Waiting for the 'Spotlight' label element")
            spotlight_label = self.locate_element(
                step="spotlight_label",
                condition=EC.presence_of_element_located((By.XPATH, '//label[.//span[text()="Spotlight"]]')),
                wait_time_seconds=6
            )
            print("Clicking the 'Spotlight' label element")
            spotlight_label.click()
            
            print("Waiting for the close button")
            close_button = self.locate_element(
                step="close_button",
                condition=EC.presence_of_element_located((By.CSS_SELECTOR, 'button[aria-label="Close"]')),
                wait_time_seconds=6
            )
            print("Clicking the close button")
            close_button.click()

        # If it's a UI exception, pass it up the chain
        except UiException as e:
            raise e

        # If it's a miscellaneous exception, raise a fatal UI exception
        except Exception as e:
            print(f"Miscellaneous exception happened in attempt_to_join_meeting: {e}")
            raise UiFatalException(f"Miscellaneous exception happened in attempt_to_join_meeting: {e.__class__.__name__}")
