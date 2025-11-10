from fastapi import FastAPI, WebSocket
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
import lgpio
import asyncio
import io
import os
import cv2
import numpy as np
from picamera2 import Picamera2


app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, specify your frontend URL
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# GPIO setup
GPIO_CHIP = 0  # Usually 0 for Raspberry Pi
LED_PIN = 17  # GPIO pin 17 for LED
h = lgpio.gpiochip_open(GPIO_CHIP)
lgpio.gpio_claim_output(h, LED_PIN)

# Camera setup
camera = Picamera2()
camera.configure(camera.create_preview_configuration(main={"size": (640, 480)}))
camera.start()

# Store LED state
led_state = False

# REST endpoint: Turn LED on/off
@app.post("/gpio/led/{state}")
async def control_led(state: str):
    global led_state
    if state == "on":
        lgpio.gpio_write(h, LED_PIN, 1)  # Set pin HIGH
        led_state = True
    elif state == "off":
        lgpio.gpio_write(h, LED_PIN, 0)  # Set pin LOW
        led_state = False
    else:
        return {"error": "Invalid state. Use 'on' or 'off'"}
    
    return {"led": state, "success": True}


# REST endpoint: Get LED status
@app.get("/gpio/led/status")
async def get_led_status():
    return {"led": "on" if led_state else "off"}


# REST endpoint: Capture single image
@app.get("/camera/capture")
async def capture_image():
    # Capture image to memory
    stream = io.BytesIO()
    camera.capture_file(stream, format='png')
    stream.seek(0)
    
    return StreamingResponse(stream, media_type="image/jpeg")

@app.get("/camera/stream")
async def video_stream():
    def generate():
        while True:
            # Capture frame from camera
            frame = camera.capture_array()
            
            # Convert to JPEG
            _, buffer = cv2.imencode('.jpg', frame)
            frame_bytes = buffer.tobytes()
            
            # Yield frame in multipart format
            yield (b'--frame\r\n'
                   b'Content-Type: image/jpeg\r\n\r\n' + frame_bytes + b'\r\n')
    
    return StreamingResponse(generate(), media_type="multipart/x-mixed-replace; boundary=frame")

# WebSocket: Real-time status updates
@app.websocket("/ws/status")
async def websocket_status(websocket: WebSocket):
    await websocket.accept()
    try:
        while True:
            # Send status every 2 seconds
            status = {
                "led": "on" if led_state else "off",
                "timestamp": asyncio.get_event_loop().time()
            }
            await websocket.send_json(status)
            await asyncio.sleep(2)
    except Exception as e:
        print(f"WebSocket error: {e}")
    finally:
        await websocket.close()


# Cleanup on shutdown
@app.on_event("shutdown")
async def shutdown():
    lgpio.gpio_write(h, LED_PIN, 0)
    lgpio.gpiochip_close(h)
    camera.stop()