import asyncio

from httpx import AsyncClient

from app.main import app


async def main():
    async with AsyncClient(app=app, base_url="http://test") as ac:
        response = await ac.get("/api/v1/annotations?document_id=test")
        print(response.status_code)
        print(response.json())

if __name__ == "__main__":
    asyncio.run(main())
