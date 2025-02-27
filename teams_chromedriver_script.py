import asyncio
import os
import subprocess
import click
import datetime
import requests
import json
import threading
import wave
import numpy as np
import cv2

from time import sleep

import undetected_chromedriver as uc
from pyvirtualdisplay import Display

from selenium.webdriver.common.keys import Keys
from selenium.webdriver.common.by import By
import websockets
from websockets.sync.server import serve
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

def handle_websocket(websocket):
    audio_file = None
    audio_format = None
    frame_counter = 0  # Add frame counter
    output_dir = 'frames'  # Add output directory
    
    # Create frames directory if it doesn't exist
    os.makedirs(output_dir, exist_ok=True)
    
    try:
        for message in websocket:
            # Get first 4 bytes as message type
            message_type = int.from_bytes(message[:4], byteorder='little')
            
            if message_type == 1:  # JSON
                json_data = json.loads(message[4:].decode('utf-8'))
                print("Received JSON message:", json_data)
                
                # Handle audio format information
                if isinstance(json_data, dict):
                    if json_data.get('type') == 'AudioFormatUpdate':
                        audio_format = json_data['format']
                        # Create a new WAV file
                        audio_file = wave.open('recorded_audio.wav', 'wb')
                        audio_file.setnchannels(audio_format['numberOfChannels'])
                        audio_file.setsampwidth(4)  # 4 bytes for float32
                        audio_file.setframerate(audio_format['sampleRate']/2)
                    
            elif message_type == 2:  # VIDEO
                if len(message) > 24:  # Minimum length check
                    # Bytes 4-12 contain the timestamp
                    timestamp = int.from_bytes(message[4:12], byteorder='little')

                    # Get stream ID length and string
                    stream_id_length = int.from_bytes(message[12:16], byteorder='little')
                    stream_id = message[16:16+stream_id_length].decode('utf-8')

                    # Get width and height after stream ID
                    offset = 16 + stream_id_length
                    width = int.from_bytes(message[offset:offset+4], byteorder='little')
                    height = int.from_bytes(message[offset+4:offset+8], byteorder='little')

                    print("width", width)
                    print("height", height)
                    print("stream_id", stream_id)
                    
                    # Convert I420 format to BGR for OpenCV
                    video_data = np.frombuffer(message[offset+8:], dtype=np.uint8)
                    
                    # Calculate sizes for Y, U, and V planes
                    y_size = width * height
                    uv_size = (width // 2) * (height // 2)
                    
                    # Extract Y, U, and V planes
                    y_plane = video_data[:y_size].reshape(height, width)
                    u_plane = video_data[y_size:y_size + uv_size].reshape(height // 2, width // 2)
                    v_plane = video_data[y_size + uv_size:y_size + 2 * uv_size].reshape(height // 2, width // 2)
                    
                    # Upscale U and V planes
                    u_plane = cv2.resize(u_plane, (width, height))
                    v_plane = cv2.resize(v_plane, (width, height))
                    
                    # Stack planes and convert to BGR
                    yuv = cv2.merge([y_plane, u_plane, v_plane])
                    bgr = cv2.cvtColor(yuv, cv2.COLOR_YUV2BGR)
                    
                    # Instead of writing to video file, save as image
                    frame_path = os.path.join(output_dir, f'frame_{frame_counter:06d}_{stream_id}.png')
                    #cv2.imwrite(frame_path, bgr)
                    frame_counter += 1
                    
            elif message_type == 3:  # AUDIO
                if audio_file is not None and len(message) > 12:
                    # Bytes 4-12 contain the timestamp
                    timestamp = int.from_bytes(message[4:12], byteorder='little')
                    # Convert the float32 audio data to int16 for WAV file
                    audio_data = np.frombuffer(message[12:], dtype=np.float32)
                    audio_data_int16 = (audio_data * 32767).astype(np.int16)
                    audio_file.writeframes(audio_data_int16.tobytes())
                    
    except Exception as e:
        print(f"Websocket error: {e}")
    finally:
        if audio_file:
            audio_file.close()

def run_websocket_server():
    # Create a new event loop for this thread
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    
    # Increase max_size parameter to handle larger video frames (set to 10MB)
    with serve(handle_websocket, "localhost", 8097, max_size=10_000_000) as server:
        print("Websocket server started on ws://localhost:8097")
        server.serve_forever()

async def join_meet():
    # Check if running in a headless environment (no display)
    if os.environ.get('DISPLAY') is None:
        # Create virtual display only if no real display is available
        display = Display(visible=0, size=(1920, 1080))
        display.start()
    
    # Start websocket server in a separate thread
    websocket_thread = threading.Thread(target=run_websocket_server, daemon=True)
    websocket_thread.start()
    
    meet_link = "https://teams.live.com/meet/9387312584033?p=GaiE7wxwaV3rDFwpgr"
    print(f"start recorder for {meet_link}")

    options = uc.ChromeOptions()

    options.add_argument("--use-fake-ui-for-media-stream")
    options.add_argument("--window-size=1920x1080")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-setuid-sandbox")
    # options.add_argument('--headless=new')
    options.add_argument("--disable-gpu")
    options.add_argument("--disable-extensions")
    options.add_argument("--disable-application-cache")
    options.add_argument("--disable-setuid-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    log_path = "chromedriver.log"

    driver = uc.Chrome(service_log_path=log_path, use_subprocess=False, options=options)

    driver.set_window_size(1920, 1080)

    # Define the CDN libraries needed
    CDN_LIBRARIES = [
        'https://cdnjs.cloudflare.com/ajax/libs/protobufjs/7.4.0/protobuf.min.js',
        'https://cdnjs.cloudflare.com/ajax/libs/pako/2.1.0/pako.min.js'
    ]

    # Download all library code
    libraries_code = ""
    for url in CDN_LIBRARIES:
        response = requests.get(url)
        if response.status_code == 200:
            libraries_code += response.text + "\n"
        else:
            raise Exception(f"Failed to download library from {url}")
    
    # Read your payload
    with open('teams_chromedriver_payload.js', 'r') as file:
        payload_code = file.read()
    
    # Combine them ensuring libraries load first
    combined_code = f"""
        {libraries_code}
        {payload_code}
    """
    
    # Add the combined script to execute on new document
    driver.execute_cdp_cmd('Page.addScriptToEvaluateOnNewDocument', {
        'source': combined_code
    })

    driver.get(meet_link)

    driver.execute_cdp_cmd(
        "Browser.grantPermissions",
        {
            "origin": meet_link,
            "permissions": [
                "geolocation",
                "audioCapture",
                "displayCapture",
                "videoCapture",
            ],
        },
    )

    print("Waiting for the name input field...")
    name_input = WebDriverWait(driver, 60).until(
        EC.presence_of_element_located((By.CSS_SELECTOR, '[data-tid="prejoin-display-name-input"]'))
    )
    
    print("Waiting for 1 second...")
    sleep(1)
    
    print("Filling the input field with the name...")
    full_name = "Mr Bot!"
    name_input.send_keys(full_name)
    
    print("Waiting for the Join now button...")
    join_button = driver.find_element(By.CSS_SELECTOR, '[data-tid="prejoin-join-button"]')
    
    print("Clicking the Join now button...")
    join_button.click()

    print("Waiting for the show more button...")
    show_more_button = WebDriverWait(driver, 600).until(
        EC.presence_of_element_located((By.ID, 'callingButtons-showMoreBtn'))
    )
    print("Clicking the show more button...")
    show_more_button.click()

    print("Waiting for the Language and Speech button...")
    language_and_speech_button = WebDriverWait(driver, 600).until(
        EC.presence_of_element_located((By.ID, 'LanguageSpeechMenuControl-id'))
    )
    print("Clicking the language and speech button...")
    language_and_speech_button.click()

    print("Waiting for the closed captions button...")
    closed_captions_button = WebDriverWait(driver, 600).until(
        EC.presence_of_element_located((By.ID, 'closed-captions-button'))
    )
    print("Clicking the closed captions button...")
    closed_captions_button.click()    

    print("- End of work")
    sleep(10000)


if __name__ == "__main__":
    click.echo("starting teams recorder...")
    asyncio.run(join_meet())
    click.echo("finished recording teams.")