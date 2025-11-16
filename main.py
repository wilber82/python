from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from PIL import Image
from picamera2 import Picamera2
import lgpio, psutil, asyncio,io,os

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
LED_PIN = 18  # GPIO pin 17 for LED
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
    
    return StreamingResponse(stream, media_type="image/png")

@app.get("/camera/stream")
async def video_stream():
    def generate():
        while True:
            # Capture frame as array
            frame = camera.capture_array()
            
            # Encode to JPEG using PIL
            image = Image.fromarray(frame)
            
            # Convert RGBA to RGB if necessary
            if image.mode == 'RGBA':
                image = image.convert('RGB')
            
            buffer = io.BytesIO()
            image.save(buffer, format='JPEG')
            frame_bytes = buffer.getvalue()
            
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
            try:
                cpu_usage = await asyncio.to_thread(psutil.cpu_percent, interval=1)
                mem = psutil.virtual_memory()
                disk = psutil.disk_usage('/')
                mem_usage = mem.percent
                disk_usage = disk.percent
            except OSError:
                cpu_usage = 0.0
            # Send status every 2 seconds
            status = {
                "led": "on" if led_state else "off",
                "timestamp": asyncio.get_event_loop().time(),
                "cpu_usage": cpu_usage,
                "cpu_cores": os.cpu_count(),
                "cpu_model": os.uname().machine,
                "cpu_temp": os.popen("vcgencmd measure_temp").readline().replace("temp=","").replace("'C\n",""),
                "memory_usage": mem_usage,
                "disk_usage": disk_usage
            }
            await websocket.send_json(status)
            await asyncio.sleep(1)
    except WebSocketDisconnect:
        print("WebSocket client disconnected")
    except Exception as e:
        print(f"WebSocket error: {e}")
    finally:
        try:
            await websocket.close()
        except RuntimeError:
            # close already sent, ignore
            pass


# Cleanup on shutdown
@app.on_event("shutdown")
async def shutdown():
    lgpio.gpio_write(h, LED_PIN, 0)
    lgpio.gpiochip_close(h)
    camera.stop()