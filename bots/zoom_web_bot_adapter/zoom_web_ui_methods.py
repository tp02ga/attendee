class ZoomWebUIMethods:
    def __init__(self, driver):
        self.driver = driver

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
                ],
            },
        )


import os
from datetime import datetime, timedelta
import jwt    

def zoom_meeting_sdk_signature(
    meeting_number: str | int,
    role: int,
    *,
    expiration_seconds: int = 24 * 60 * 60,      # default 2 h
    video_webrtc_mode: int | None = None,
    sdk_key: str | None = None,
    sdk_secret: str | None = None,
) -> dict[str, str]:
    """
    Create a Zoom Meeting SDK JWT signature.

    Parameters
    ----------
    meeting_number : str | int
    role           : 0 for attendee, 1 for host
    expiration_seconds : lifetime for the token (min 1 800, max 172 800)
    video_webrtc_mode  : 0 or 1 (optional)
    sdk_key, sdk_secret: if omitted, read from env vars
                         ZOOM_MEETING_SDK_KEY / ZOOM_MEETING_SDK_SECRET

    Returns
    -------
    {"signature": "<jwt>", "sdkKey": "<sdk_key>"}
    """

    sdk_key    = sdk_key    or os.getenv("ZOOM_MEETING_SDK_KEY")
    sdk_secret = sdk_secret or os.getenv("ZOOM_MEETING_SDK_SECRET")
    if not sdk_key or not sdk_secret:
        raise RuntimeError("SDK key/secret missing (env vars or arguments)")

    iat = int(datetime.utcnow().timestamp())
    exp = iat + expiration_seconds

    payload = {
        "appKey":   sdk_key,
        "sdkKey":   sdk_key,
        "mn":       str(meeting_number),
        "role":     role,
        "iat":      iat,
        "exp":      exp,
        "tokenExp": exp,
    }
    if video_webrtc_mode is not None:
        payload["video_webrtc_mode"] = video_webrtc_mode

    token = jwt.encode(payload, sdk_secret, algorithm="HS256")
    return {"signature": token, "sdkKey": sdk_key}