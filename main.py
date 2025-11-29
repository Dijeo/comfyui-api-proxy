import uvicorn
from fastapi import FastAPI, Request, WebSocket, HTTPException, Depends, Security, UploadFile, File, Form
from fastapi.security.api_key import APIKeyHeader
from fastapi.responses import StreamingResponse, Response
import httpx
import asyncio
import websockets
from starlette.websockets import WebSocketDisconnect
from starlette.status import HTTP_403_FORBIDDEN
import os
import json
from typing import Optional
from utils import load_workflow_template, update_workflow_inputs
from comfy_client import ComfyClient

app = FastAPI()

COMFY_HOST = os.getenv("COMFY_HOST", "127.0.0.1")
COMFY_PORT = os.getenv("COMFY_PORT", "7337")
COMFY_BASE_URL = os.getenv("COMFY_BASE_URL", f"http://{COMFY_HOST}:{COMFY_PORT}")
COMFY_WS_URL = os.getenv("COMFY_WS_URL", f"ws://{COMFY_HOST}:{COMFY_PORT}")
API_KEY = os.getenv("COMFY_API_KEY", "secret-key") # Default key for dev
API_KEY_NAME = "X-API-Key"

api_key_header = APIKeyHeader(name=API_KEY_NAME, auto_error=False)

# Global HTTP client for proxying
http_client = httpx.AsyncClient(base_url=COMFY_BASE_URL, timeout=None)

async def get_api_key(api_key_header: str = Security(api_key_header)):
    if api_key_header == API_KEY:
        return api_key_header
    raise HTTPException(
        status_code=HTTP_403_FORBIDDEN, detail="Could not validate credentials"
    )

@app.on_event("shutdown")
async def shutdown_event():
    await http_client.aclose()

@app.post("/upload", dependencies=[Depends(get_api_key)])
async def upload_image(image: UploadFile = File(...), overwrite: bool = Form(False)):
    """
    Uploads an image to ComfyUI for use in workflows.
    Returns the filename to be used in workflow inputs.
    """
    client = ComfyClient(COMFY_BASE_URL, COMFY_WS_URL)
    try:
        file_content = await image.read()
        resp = await client.upload_image(file_content, image.filename, overwrite=overwrite)
        return resp
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        await client.close()

@app.post("/run_workflow", dependencies=[Depends(get_api_key)])
async def run_workflow(workflow: dict):
    """
    Executes a raw ComfyUI workflow (API format).
    Returns the generated content (Image, Video, etc.) based on the output filename.
    """
    client = ComfyClient(COMFY_BASE_URL, COMFY_WS_URL)
    try:
        # Execute synchronously
        data, filename = await client.execute_workflow(workflow)
        
        # Determine media type
        ext = os.path.splitext(filename)[1].lower()
        media_type = "application/octet-stream"
        if ext in [".png", ".jpg", ".jpeg", ".webp"]:
            media_type = f"image/{ext[1:]}"
        elif ext in [".mp4", ".webm", ".mov", ".mkv"]:
            media_type = f"video/{ext[1:]}"
        elif ext in [".txt", ".json"]:
            media_type = "text/plain"
            
        # Add filename to headers so client knows what it got
        headers = {"Content-Disposition": f'attachment; filename="{filename}"'}
        
        return Response(content=data, media_type=media_type, headers=headers)
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        await client.close()

@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    # WebSocket auth is tricky with headers, often done via query param or protocol
    # For simplicity, we'll check query param 'token' or just allow if trusted network
    # But to be consistent, let's check a query param
    token = ws.query_params.get("token")
    if token != API_KEY:
         await ws.close(code=1008)
         return

    await ws.accept()
    try:
        async with websockets.connect(f"{COMFY_WS_URL}/ws") as comfy_ws:
            
            async def forward_to_comfy():
                try:
                    while True:
                        message = await ws.receive()
                        if "text" in message:
                            await comfy_ws.send(message["text"])
                        elif "bytes" in message:
                            await comfy_ws.send(message["bytes"])
                except WebSocketDisconnect:
                    pass
                except Exception as e:
                    print(f"Error forwarding to Comfy: {e}")

            async def forward_to_client():
                try:
                    while True:
                        data = await comfy_ws.recv()
                        if isinstance(data, str):
                            await ws.send_text(data)
                        else:
                            await ws.send_bytes(data)
                except websockets.exceptions.ConnectionClosed:
                    pass
                except Exception as e:
                    print(f"Error forwarding to client: {e}")

            await asyncio.gather(forward_to_comfy(), forward_to_client())
            
    except Exception as e:
        print(f"WebSocket connection error: {e}")
        await ws.close()

@app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "OPTIONS", "HEAD", "PATCH"], dependencies=[Depends(get_api_key)])
async def proxy(request: Request, path: str):
    url = httpx.URL(path=path, query=request.url.query.encode("utf-8"))
    
    # Exclude headers that might cause issues
    excluded_headers = {"host", "content-length", "x-api-key"}
    headers = {
        key: value 
        for key, value in request.headers.items() 
        if key.lower() not in excluded_headers
    }
    
    try:
        # Read the body
        content = await request.body()
        
        req = http_client.build_request(
            request.method,
            url,
            headers=headers,
            content=content
        )
        
        r = await http_client.send(req, stream=True)
        
        return StreamingResponse(
            r.aiter_raw(),
            status_code=r.status_code,
            headers=r.headers,
            background=r.aclose
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8189)
