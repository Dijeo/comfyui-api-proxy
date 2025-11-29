import httpx
import asyncio
import sys

async def verify():
    headers = {"X-API-Key": "secret-key"}
    async with httpx.AsyncClient() as client:
        try:
            print("Checking proxy root with valid key...")
            resp = await client.get("http://127.0.0.1:8189/", headers=headers)
            print(f"Root status: {resp.status_code}")
            
            # If ComfyUI is running, we expect 200. If not, 500 (connection error).
            if resp.status_code == 200:
                print("Success: Proxy reachable and ComfyUI seems up.")
            elif resp.status_code == 500:
                print("Proxy reachable, but ComfyUI might be down (got 500).")
            else:
                print(f"Unexpected status: {resp.status_code}")

            print("\nChecking proxy root WITHOUT key...")
            resp_no_key = await client.get("http://127.0.0.1:8189/")
            print(f"Status without key: {resp_no_key.status_code}")
            if resp_no_key.status_code == 403:
                print("Success: Authentication rejected missing key.")
            else:
                print("Failure: Authentication did not reject missing key.")

        except httpx.ConnectError:
            print("Failed to connect to proxy at http://127.0.0.1:8189. Is it running?")
            sys.exit(1)
        except Exception as e:
            print(f"Error: {e}")
            sys.exit(1)

if __name__ == "__main__":
    asyncio.run(verify())
