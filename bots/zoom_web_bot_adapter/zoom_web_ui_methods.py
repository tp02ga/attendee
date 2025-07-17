import os

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
