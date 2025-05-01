class VideoOutputManager:
    def __init__(
        self,
        currently_playing_video_media_request_finished_callback,
        check_if_currently_playing_video_media_request_is_still_playing_callback,
        play_video_callback,
    ):
        self.currently_playing_video_media_request = None
        self.currently_playing_video_media_request_finished_callback = currently_playing_video_media_request_finished_callback
        self.check_if_currently_playing_video_media_request_is_still_playing_callback = check_if_currently_playing_video_media_request_is_still_playing_callback
        self.play_video_callback = play_video_callback

    def start_playing_video_media_request(self, video_media_request):
        self.currently_playing_video_media_request = video_media_request
        self.play_video_callback(video_media_request.media_url)

    def monitor_currently_playing_video_media_request(self):
        if not self.currently_playing_video_media_request:
            return
        if self.check_if_currently_playing_video_media_request_is_still_playing_callback():
            return
        self.currently_playing_video_media_request_finished_callback(self.currently_playing_video_media_request)
        self.currently_playing_video_media_request = None
