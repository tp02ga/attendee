import subprocess
import signal

class DebugScreenRecorder:
    def __init__(self, display_var, screen_dimensions, output_file_path):
        self.display_var = display_var
        self.screen_dimensions = screen_dimensions
        self.output_file_path = output_file_path
        self.ffmpeg_proc = None

    def start(self):
        self.ffmpeg_proc = subprocess.Popen(
            [
                "ffmpeg",
                "-y",
                "-f", "x11grab",
                "-video_size", f"{self.screen_dimensions[0]}x{self.screen_dimensions[1]}",
                "-i", self.display_var,
                "-pix_fmt", "yuv420p",
                self.output_file_path
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.STDOUT
        )

    def stop(self):
        if not self.ffmpeg_proc:
            return
        self.ffmpeg_proc.terminate()
        self.ffmpeg_proc.wait()
