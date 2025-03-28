import logging
import subprocess

logger = logging.getLogger(__name__)


class DebugScreenRecorder:
    def __init__(self, display_var, screen_dimensions, output_file_path):
        self.display_var = display_var
        self.screen_dimensions = screen_dimensions
        self.output_file_path = output_file_path
        self.ffmpeg_proc = None

    def start(self):
        logger.info(f"Starting debug screen recorder for display {self.display_var} with dimensions {self.screen_dimensions} and output file path {self.output_file_path}")
        ffmpeg_cmd = [
            "ffmpeg",
            "-y",  # Overwrite output file if it exists
            # --- Video Input ---
            "-f", "x11grab",
            "-framerate", "30",    # Add explicit framerate (30fps)
            "-video_size", f"{self.screen_dimensions[0]}x{self.screen_dimensions[1]}",
            "-i", self.display_var,
            # --- Audio Input ---
            "-f", "pulse",
            "-i", "VirtualSpeaker.monitor",
            # --- Output Settings ---
            "-pix_fmt", "yuv420p",  # Video pixel format
            "-c:v", "libx264",      # Video codec
            "-preset", "ultrafast",  # Prioritize speed over compression
            "-crf", "23",           # Constant Rate Factor (lower = better quality)
            "-tune", "zerolatency", # Reduce encoding latency
            "-r", "30",             # Output framerate
            "-c:a", "aac",          # Audio codec
            "-b:a", "128k",         # Audio bitrate
            self.output_file_path
        ]
        logger.info(f"Starting FFmpeg command: {' '.join(ffmpeg_cmd)}")
        self.ffmpeg_proc = subprocess.Popen(ffmpeg_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)

    def stop(self):
        if not self.ffmpeg_proc:
            return
        self.ffmpeg_proc.terminate()
        self.ffmpeg_proc.wait()
        logger.info(f"Stopped debug screen recorder for display {self.display_var} with dimensions {self.screen_dimensions} and output file path {self.output_file_path}")
