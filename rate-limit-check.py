import httpx, asyncio, yaml

async def check():
    with open('/app/config/config.prod.yaml') as f:
        config = yaml.safe_load(f)
    token = config['huggingface']['token']
    print(f'Token: {token[:10]}...' if token else 'No token')
    
    headers = {'Authorization': f'Bearer {token}'} if token else {}
    client = httpx.AsyncClient(base_url='https://huggingface.co', headers=headers)
    resp = await client.get('/api/models?limit=1')
    print(f'Status: {resp.status_code}')
    print(f'RateLimit: {resp.headers.get(\"ratelimit\")}')
    await client.aclose()

asyncio.run(check())
