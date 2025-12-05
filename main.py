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
from dotenv import load_dotenv

load_dotenv()

from contextlib import asynccontextmanager

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    yield
    # Shutdown
    print("Shutting down proxy...")
    client = ComfyClient(COMFY_BASE_URL, COMFY_WS_URL)
    try:
        print("Interrupting running workflows...")
        # Use a short timeout for cleanup to avoid hanging
        await client.interrupt(timeout=0.5)
        await client.clear_queue(timeout=0.5)
        await client.free_memory(timeout=0.5)
    except Exception as e:
        print(f"Error during cleanup: {e}")
    finally:
        await client.close()
        await http_client.aclose()

app = FastAPI(lifespan=lifespan)

import secrets

COMFY_HOST = os.getenv("COMFY_HOST", "127.0.0.1")
COMFY_PORT = os.getenv("COMFY_PORT", "7337")
COMFY_BASE_URL = os.getenv("COMFY_BASE_URL", f"http://{COMFY_HOST}:{COMFY_PORT}")
COMFY_WS_URL = os.getenv("COMFY_WS_URL", f"ws://{COMFY_HOST}:{COMFY_PORT}")

print(f"----------------------------------------------------------------")
print(f"Starting Proxy with configuration:")
print(f"COMFY_HOST: {COMFY_HOST}")
print(f"COMFY_PORT: {COMFY_PORT}")
print(f"COMFY_BASE_URL: {COMFY_BASE_URL}")
print(f"COMFY_WS_URL: {COMFY_WS_URL}")
print(f"----------------------------------------------------------------")

# Generate a random key if not set
if "COMFY_API_KEY" not in os.environ:
    generated_key = secrets.token_urlsafe(32)
    print(f"\n{'='*60}")
    print(f"WARNING: COMFY_API_KEY not set. Generated random key:")
    print(f"Key: {generated_key}")
    print(f"{'='*60}\n")
    API_KEY = generated_key
else:
    API_KEY = os.environ["COMFY_API_KEY"]

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
async def run_workflow(workflow: dict, request: Request):
    """
    Executes a raw ComfyUI workflow (API format).
    Returns the generated content (Image, Video, etc.) based on the output filename.
    """
    client = ComfyClient(COMFY_BASE_URL, COMFY_WS_URL)
    try:
        # Execute synchronously
        # We use asyncio.wait_for to allow checking for client disconnects if needed,
        # but execute_workflow is already async.
        # To handle disconnects, we can check request.is_disconnected() periodically
        # or rely on asyncio.CancelledError if the server cancels the task.
        
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
        
    except asyncio.CancelledError:
        print("Request cancelled by client. Interrupting ComfyUI...")
        await client.interrupt()
        await client.clear_queue()
        await client.free_memory()
        raise HTTPException(status_code=499, detail="Request cancelled")
    except Exception as e:
        # On error, we might want to cleanup too
        print(f"Error executing workflow: {e}")
        await client.interrupt()
        await client.clear_queue()
        await client.free_memory()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        await client.close()

@app.post("/run_workflow_stream", dependencies=[Depends(get_api_key)])
async def run_workflow_stream(workflow: dict, request: Request):
    """
    Executes a workflow and streams progress events (SSE).
    Events: 'progress', 'executing', 'execution_start', 'execution_cached', 'result', 'error'.
    """
    client = ComfyClient(COMFY_BASE_URL, COMFY_WS_URL)
    
    async def event_generator():
        try:
            async for event in client.execute_workflow_stream(workflow):
                # Check for client disconnect
                if await request.is_disconnected():
                    print("Client disconnected, cancelling...")
                    await client.interrupt()
                    break
                
                yield f"data: {json.dumps(event)}\n\n"
        except Exception as e:
            print(f"Error in stream: {e}")
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"
        finally:
            await client.close()

    return StreamingResponse(event_generator(), media_type="text/event-stream")

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
