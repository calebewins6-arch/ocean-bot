import fortnitepy, json, asyncio

async def main():
    client = fortnitepy.Client(
        auth=fortnitepy.AuthorizationCodeAuth(
            code=input("Paste your auth code: ").strip()
        )
    )

    @client.event
    async def event_ready():
        creds = await client.auth.generate_device_auth()
        with open("device_auth.json", "w") as f:
            json.dump(creds, f, indent=2)
        print("Saved to device_auth.json!")
        await client.close()

    await client.start()

asyncio.run(main())
