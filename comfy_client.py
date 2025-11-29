import uuid
import json
import asyncio
import websockets
import httpx
from typing import Optional, Dict, Any

class ComfyClient:
    def __init__(self, base_url: str, ws_url: str):
        self.base_url = base_url
        self.ws_url = ws_url
        self.client_id = str(uuid.uuid4())
        self.http_client = httpx.AsyncClient(base_url=base_url, timeout=None)

    async def close(self):
        await self.http_client.aclose()

    async def queue_prompt(self, prompt: Dict[str, Any]) -> str:
        payload = {"prompt": prompt, "client_id": self.client_id}
        resp = await self.http_client.post("/prompt", json=payload)
        resp.raise_for_status()
        return resp.json()["prompt_id"]

    async def get_history(self, prompt_id: str) -> Dict[str, Any]:
        resp = await self.http_client.get(f"/history/{prompt_id}")
        resp.raise_for_status()
        return resp.json()[prompt_id]

    async def get_image(self, filename: str, subfolder: str, folder_type: str) -> bytes:
        params = {"filename": filename, "subfolder": subfolder, "type": folder_type}
        resp = await self.http_client.get("/view", params=params)
        resp.raise_for_status()
        return resp.content

    async def execute_workflow(self, workflow: Dict[str, Any]) -> tuple[bytes, str]:
        """
        Executes a workflow synchronously:
        1. Connects to WS
        2. Queues prompt
        3. Waits for completion
        4. Downloads and returns the first output image
        """
        async with websockets.connect(f"{self.ws_url}/ws?clientId={self.client_id}") as ws:
            prompt_id = await self.queue_prompt(workflow)
            print(f"Queued prompt: {prompt_id}")

            while True:
                out = await ws.recv()
                if isinstance(out, str):
                    message = json.loads(out)
                    # print(f"WS Message: {message['type']}")
                    
                    if message['type'] == 'executing':
                        data = message['data']
                        if data['node'] is None and data['prompt_id'] == prompt_id:
                            # Execution finished
                            break
            
            # Execution finished, fetch history to get images
            history = await self.get_history(prompt_id)
            outputs = history.get("outputs", {})
            
            # Find the first image output
            # outputs is a dict where key is node_id
            for node_id, node_output in outputs.items():
                if "images" in node_output:
                    image_info = node_output["images"][0]
                    filename = image_info["filename"]
                    subfolder = image_info["subfolder"]
                    folder_type = image_info["type"]
                    
                    print(f"Downloading image: {filename}")
                    image_data = await self.get_image(filename, subfolder, folder_type)
                    return image_data, filename
            
            raise Exception("No image output found in workflow history")

    async def upload_image(self, file_data: bytes, filename: str, overwrite: bool = False) -> Dict[str, Any]:
        """
        Uploads an image to ComfyUI.
        Returns the response dict containing 'name', 'subfolder', 'type'.
        """
        files = {"image": (filename, file_data)}
        data = {"overwrite": str(overwrite).lower()}
        resp = await self.http_client.post("/upload/image", files=files, data=data)
        resp.raise_for_status()
        return resp.json()
