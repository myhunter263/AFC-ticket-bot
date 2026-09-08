import json
from urllib.parse import quote

import aiohttp


class BackendError(RuntimeError):
    pass


class BackendClient:
    def __init__(self, url, token):
        self.url = url.rstrip("/")
        self.token = token
        self.session = None

    async def start(self):
        self.session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=120))

    async def close(self):
        if self.session:
            await self.session.close()

    def headers(self, member=None):
        headers = {"Authorization": f"Bearer {self.token}"}
        if member is not None:
            headers.update({"X-Discord-User-Id": str(member.id), "X-Discord-Name": quote(str(member)),
                            "X-Discord-Roles": ",".join(str(r.id) for r in member.roles),
                            "X-Discord-Administrator": str(member.guild_permissions.administrator).lower()})
        return headers

    async def request(self, method, path, *, member=None, data=None, params=None):
        try:
            async with self.session.request(method, self.url + path, headers=self.headers(member),
                                            json=data, params=params, allow_redirects=False) as response:
                payload = await response.json(content_type=None)
                if response.status >= 300:
                    detail = payload.get("detail", "Ошибка backend")
                    raise BackendError(detail if isinstance(detail, str) else "Проверьте введённые значения")
                return payload
        except (aiohttp.ClientError, TimeoutError, ValueError) as exc:
            raise BackendError("Backend недоступен. Попробуйте ещё раз") from exc

    async def events(self, after=0):
        url = self.url.replace("https://", "wss://", 1).replace("http://", "ws://", 1)
        async with self.session.ws_connect(url + "/api/v1/events", heartbeat=30) as ws:
            await ws.send_json({"token": self.token, "after": after})
            async for message in ws:
                if message.type == aiohttp.WSMsgType.TEXT:
                    yield json.loads(message.data)
                elif message.type == aiohttp.WSMsgType.ERROR:
                    raise BackendError("Соединение событий прервано")
