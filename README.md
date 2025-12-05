# ComfyUI API Proxy

A lightweight Python FastAPI proxy that exposes a local [ComfyUI](https://github.com/comfyanonymous/ComfyUI) instance to the network with authentication and simplified workflow execution.

## Features

- **Remote Access**: Access your local ComfyUI from other devices on the network.
- **Authentication**: Secure your endpoint with API Key authentication (`X-API-Key`).
- **Synchronous Execution**: Queue a workflow and wait for the result in a single HTTP request.
- **Dynamic Output**: Automatically detects and returns the generated image, video, or text.
- **Progress Tracking**: Stream real-time progress updates via Server-Sent Events (SSE).
- **Graceful Shutdown**: Automatically interrupts running workflows and frees VRAM when the proxy stops.
- **Image Upload**: Helper endpoint to upload images for Image-to-Image or Image-to-Video workflows.

## Prerequisites

- Python 3.10+
- A running instance of ComfyUI (default port 7337, configurable)
- **Important**: If running via Docker, ComfyUI must be started with `--listen` to accept connections from the container.

## Installation

1.  **Clone the repository**:
    ```bash
    git clone https://github.com/yourusername/comfyui-api-proxy.git
    cd comfyui-api-proxy
    ```

2.  **Create a virtual environment** (Recommended):
    ```bash
    python -m venv venv
    # Windows
    .\venv\Scripts\activate
    # Linux/Mac
    source venv/bin/activate
    ```

3.  **Install dependencies**:
    ```bash
    pip install -r requirements.txt
    ```

## Configuration

You can configure the proxy using environment variables. You can either set them in your shell or create a `.env` file in the root directory:

```env
COMFY_HOST=127.0.0.1
COMFY_PORT=7337
COMFY_API_KEY=your-secret-key-here
```

| Variable | Description | Default |
| :--- | :--- | :--- |
| `COMFY_HOST` | Host where ComfyUI is running | `127.0.0.1` |
| `COMFY_PORT` | Port where ComfyUI is running | `7337` |
| `COMFY_API_KEY` | Secret key for authentication | Randomly generated if not set |
| `PORT` | Port for this proxy server | `8189` |

## Docker Deployment

You can build and run the proxy as a Docker container.

1.  **Build the image**:
    ```bash
    docker build -t comfyui-proxy .
    ```

2.  **Run the container**:
    ```bash
    # For Windows/Mac (Docker Desktop):
    docker run -p 8189:8189 \
      -e COMFY_HOST=host.docker.internal \
      -e COMFY_PORT=7337 \
      -e COMFY_API_KEY=my-secret-key \
      comfyui-proxy

    # For Linux:
    # Use your host's LAN IP (e.g., 192.168.1.100) instead of host.docker.internal
    ```
    *Note: Ensure your local ComfyUI instance is running with `--listen` (e.g., `python main.py --listen`) so it can accept connections from the Docker container.*

## Usage

1.  **Start the server (Local Python)**:
    ```bash
    python main.py
    ```
    The server will start on `http://0.0.0.0:8189`.
    **Check the console output for the generated API Key if you didn't set one.**

2.  **Important Note on Workflows**:
    > **⚠️ CRITICAL**: Before using a workflow with this API, **you MUST ensure it works natively in ComfyUI first.**
    > 1. Open ComfyUI in your browser.
    > 2. Create/Load your workflow.
    > 3. Enable "Dev Mode" in ComfyUI settings to see the "Save (API Format)" button.
    > 4. Save the workflow as API JSON.
    > 5. Use this JSON as the payload for the API.

3.  **Run a Workflow (Synchronous)**:
    Send a POST request to `/run_workflow` with your workflow JSON.

    ```bash
    curl -X POST "http://localhost:8189/run_workflow" \
         -H "X-API-Key: secret-key" \
         -H "Content-Type: application/json" \
         -d @your_workflow_api.json \
         --output result.png
    ```

4.  **Run a Workflow (Streaming Progress)**:
    Send a POST request to `/run_workflow_stream` to get real-time updates via SSE.

    ```bash
    curl -N -X POST "http://localhost:8189/run_workflow_stream" \
         -H "X-API-Key: secret-key" \
         -H "Content-Type: application/json" \
         -d @your_workflow_api.json
    ```
    **Streamed Events:**
    - `event: progress` -> `data: {"type": "progress", "data": {"value": 1, "max": 10}}`
    - `event: executing` -> `data: {"type": "executing", "data": {"node": "123"}}`
    - `event: result` -> `data: {"type": "result", "data": {"filename": "...", "subfolder": "...", "type": "output"}}`

5.  **Upload an Image** (for Img2Img/Img2Vid):
    ```bash
    curl -X POST "http://localhost:8189/upload" \
         -H "X-API-Key: secret-key" \
         -F "image=@input.jpg"
    ```
    Use the returned filename in your workflow JSON (e.g., in the `LoadImage` node).

## API Endpoints

- `POST /run_workflow`: Execute a workflow and get the result (Image/Video/Text).
- `POST /run_workflow_stream`: Execute a workflow and stream progress events (SSE).
- `POST /upload`: Upload an image file.
- `GET /ws`: WebSocket proxy (requires `token` query param).
- `GET /*`: Proxy all other ComfyUI static assets and endpoints.

## Troubleshooting

### "No image/video output found"
This usually means the workflow failed to execute in ComfyUI.
1.  **Check the API Logs**: The proxy now logs the exact error from ComfyUI. Look for `ComfyUI Error`.
2.  **Verify Locally**: Run the exact same workflow JSON in ComfyUI manually. If it fails there (e.g., missing nodes, model load errors), it will fail in the proxy.
3.  **Custom Nodes**: Errors like `OSError` or `ModuleNotFound` in custom nodes (e.g., `pig.py`, `ComfyUI-GGUF`) are common. Ensure your ComfyUI environment is correctly set up and all dependencies are installed.

### Connection Refused (Docker)
If the Docker container cannot connect to ComfyUI:
1.  Ensure ComfyUI is running with `--listen` (e.g., `python main.py --listen`).
2.  Use `COMFY_HOST=host.docker.internal` (Windows/Mac) or your LAN IP (Linux).
3.  Check if a firewall is blocking the connection.

## Remote Access & NAT Forwarding

To access this API from outside your local network (e.g., over the internet), you have two main options:

### 1. Port Forwarding (NAT)
If you have a public IP address, you can forward the port on your router.
1.  Log in to your router's admin panel.
2.  Find the **Port Forwarding** / **NAT** settings.
3.  Forward external port `8189` (or your configured port) to your local machine's IP address (e.g., `192.168.1.X`) on port `8189`.
4.  You can then access the API via `http://<YOUR_PUBLIC_IP>:8189`.

> **⚠️ SECURITY WARNING**: Port forwarding exposes your machine directly to the internet. Ensure you have a strong `COMFY_API_KEY` set.

### 2. Tunneling (Recommended for Safety)
Use a service like **Ngrok** or **Cloudflare Tunnel** to expose the port without opening your router.
```bash
# Example with Ngrok
ngrok http 8189
```
This gives you a secure public URL (e.g., `https://xyz.ngrok-free.app`) that tunnels to your local API.

## License

MIT
