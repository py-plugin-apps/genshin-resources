import json
import asyncio
from io import BytesIO
from pathlib import Path
from PIL import Image, ImageMath
from typing import List, Iterator, Tuple

import httpx

Image.MAX_IMAGE_PIXELS = 2300000000
ICON_PATH = Path(__file__).absolute().parent.parent / "icon"
TRANSPORT_PATH = Path(__file__).absolute().parent.parent / "transport"


class Error(Exception):
    def __init__(self, msg):
        self.msg = msg

    def __str__(self):
        return self.msg


class Downloader:
    map_list = ['2', '7', '9', '12']
    data = {
        "transport": [],
        "all_resource_type": {},
        "can_query_type_list": {},
        "all_resource_point_list": {},
    }
    label_url = 'https://api-static.mihoyo.com/common/blackboard/ys_obc/v1/map/label/tree?app_sn=ys_obc'
    point_list_url = 'https://api-static.mihoyo.com/common/blackboard/ys_obc/v1/map/point/list?map_id=%s&app_sn=ys_obc'
    headers = 'Mozilla/4.0 (compatible; MSIE 8.0; Windows NT 5.1; Trident/4.0)'
    help_list = []

    def __init__(self, client: httpx.AsyncClient):
        self.client = client

    async def get(self, url: str, query: str = None) -> httpx.Response:
        if query:
            url = url % query
        res = await self.client.get(url, follow_redirects=True)
        return res

    async def init(self) -> None:
        await self.get_data()
        await self.get_icon()
        await self.get_transport()
        await self.get_resources()

    async def get_transport(self) -> None:
        task_list = list(filter(
            lambda x: x["id"] in self.data["transport"] and not (TRANSPORT_PATH / f"{x['id']}.png").exists(),
            self.data["all_resource_type"].values()
        ))

        if not task_list:
            return

        done, _ = await asyncio.wait(
            map(lambda x: asyncio.create_task(self.get(x["icon"]), name=x["id"]), task_list),
            timeout=10
        )

        for i in done:
            icon = Image.open(BytesIO(i.result().content))
            icon_path = TRANSPORT_PATH / f"{i.get_name()}.png"
            icon = icon.resize((150, 150))

            with open(icon_path, "wb") as icon_file:
                icon.save(icon_file)

    async def get_icon(self) -> None:
        task_list = list(filter(
            lambda x: x["icon"] and not (ICON_PATH / f"{x['id']}.png").exists(),
            self.data["all_resource_type"].values()
        ))

        if not task_list:
            return

        done, _ = await asyncio.wait(
            map(lambda x: asyncio.create_task(self.get(x["icon"]), name=x["id"]), task_list),
            timeout=10
        )

        box_alpha = Image.open(ICON_PATH / "box_alpha.png").getchannel("A")
        box = Image.open(ICON_PATH / "box.png")

        for i in done:
            icon = Image.open(BytesIO(i.result().content))
            icon_path = ICON_PATH / f"{i.get_name()}.png"
            icon = icon.resize((150, 150))

            try:
                icon_alpha = icon.getchannel("A")
                icon_alpha = ImageMath.eval("convert(a*b/256, 'L')", a=icon_alpha, b=box_alpha)
            except ValueError:
                icon_alpha = box_alpha

            icon2 = Image.new("RGBA", (150, 150), "#00000000")
            icon2.paste(icon, (0, -10))

            bg = Image.new("RGBA", (150, 150), "#00000000")
            bg.paste(icon2, mask=icon_alpha)
            bg.paste(box, mask=box)

            with open(icon_path, "wb") as icon_file:
                bg.save(icon_file)

    async def get_data(self) -> None:
        label_data = (await self.get(self.label_url)).json()
        self.data["transport"] = list(map(lambda x: x["id"], label_data["data"]["tree"][0]["children"]))
        for label in label_data["data"]["tree"]:
            help_cell = {
                "name": label["name"],
                "children": []
            }
            self.data["all_resource_type"][str(label["id"])] = label
            for sublist in label["children"]:
                self.data["all_resource_type"][str(sublist["id"])] = sublist
                if sublist["name"] in self.data["can_query_type_list"]:
                    self.data["can_query_type_list"][sublist["name"] + f"[{label['name']}]"] = str(sublist["id"])
                    help_cell["children"].append({
                        "name": sublist["name"] + f"[{label['name']}]",
                        "icon": sublist["icon"]
                    })
                else:
                    self.data["can_query_type_list"][sublist["name"]] = str(sublist["id"])
                    help_cell["children"].append({
                        "name": sublist["name"],
                        "icon": sublist["icon"]
                    })
            self.help_list.append(help_cell)

    async def get_resources(self) -> None:
        done, _ = await asyncio.wait(
            map(lambda x: asyncio.create_task(self.get(self.point_list_url % x), name=x), self.map_list),
            timeout=10
        )
        for i in done:
            data = i.result().json()["data"]["point_list"]
            for j in data:
                del j["ctime"]
                del j["author_name"]
                del j["display_state"]
            self.data["all_resource_point_list"][i.get_name()] = data

    @classmethod
    async def create(cls) -> "Downloader":
        async with httpx.AsyncClient() as client:
            downloader = cls(client)
            await downloader.init()
            return downloader


class ResourceMap:
    map_url = "https://waf-api-takumi.mihoyo.com/common/map_user/ys_obc/v1/map/info?map_id=%s&app_sn=ys_obc&lang=zh-cn"
    downloader = None
    map_cache = {
        '2': {},
        '7': {},
        '9': {},
        '12': {}
    }

    def __init__(self, client: httpx.AsyncClient, name: str, map_id: str):
        self.client = client
        try:
            self.resource_id = self.downloader.data["can_query_type_list"][name]
        except KeyError:
            raise Error(f"无法找到资源：{name}，请换个名字试试")

        self.all_resource_point_list = self.downloader.data["all_resource_point_list"][map_id]
        self.map_id = map_id
        self.center = None
        self.x_start = None
        self.y_start = None
        self.x_end = 0
        self.y_end = 0

        if (ICON_PATH / f"{self.resource_id}.png").exists():
            self.resource_icon = Image.open(ICON_PATH / f"{self.resource_id}.png")
        else:
            self.resource_icon = Image.open(ICON_PATH / "0.png")

        self.resource_icon = self.resource_icon.resize((int(150 * 0.5), int(150 * 0.5)))
        self.resource_icon_offset = (-int(150 * 0.5 * 0.5), -int(150 * 0.5))

    async def get(self, url: str, query: str = None) -> httpx.Response:
        if query:
            url = url % query
        res = await self.client.get(url, follow_redirects=True)
        return res

    async def get_map_info(self):
        return (await self.get(self.map_url % self.map_id)).json()["data"]["info"]["detail"]

    async def create_map(self, map_info) -> Image:
        map_info = json.loads(map_info)

        map_url_list = map_info['slices']
        origin = map_info["origin"]
        x_start = map_info['total_size'][1]
        y_start = map_info['total_size'][1]
        x_end = 0
        y_end = 0

        for resource_point in self.all_resource_point_list:
            x_pos = resource_point["x_pos"] + origin[0]
            y_pos = resource_point["y_pos"] + origin[1]
            x_start = min(x_start, x_pos)
            y_start = min(y_start, y_pos)
            x_end = max(x_end, x_pos)
            y_end = max(y_end, y_pos)

        x_start -= 200
        y_start -= 200
        x_end += 200
        y_end += 200

        self.center = [origin[0] - x_start, origin[1] - y_start]
        x = int(x_end - x_start)
        y = int(y_end - y_start)

        raw_map: Image = Image.new("RGB", (x, y))
        x_offset = y_offset = 0

        for map_url in map_url_list:
            done = await asyncio.gather(*map(lambda x: asyncio.create_task(self.get(x["url"])), map_url))
            _y_offset = 0
            for i in done:
                part = Image.open(BytesIO(i.content))
                raw_map.paste(part, (int(-x_start) + x_offset, int(-y_start) + y_offset))
                x_offset += part.size[0]
                _y_offset = part.size[1]

            x_offset = 0
            y_offset += _y_offset
        self.x_start, self.y_start = raw_map.size

        transport_list = filter(lambda x: x["label_id"] in self.downloader.data["transport"],
                                self.all_resource_point_list)
        raw_map = await self.paste_transport(raw_map, transport_list)

        self.map_cache[self.map_id] = {
            "map": raw_map.copy(),
            "center": self.center,
            "start": (self.x_start, self.y_start)
        }

        return raw_map

    async def paste_transport(self, img: Image, transport_list) -> Image:
        for transport in transport_list:
            x = int(transport["x_pos"] + self.center[0])
            y = int(transport["y_pos"] + self.center[1])
            label_id = transport["label_id"]
            if (ICON_PATH / f"{label_id}.png").exists():
                resource_icon = Image.open(TRANSPORT_PATH / f"{label_id}.png")
            else:
                resource_icon = Image.open(TRANSPORT_PATH / "0.png")
            resource_icon = resource_icon.resize((int(150 * 0.5), int(150 * 0.5)))
            img.paste(
                resource_icon,
                (x + self.resource_icon_offset[0], y),
                resource_icon,
            )
        return img

    async def get_resource_point_list(self) -> Iterator[Tuple[int, int]]:
        return map(
            lambda point: (int(point["x_pos"] + self.center[0]), int(point["y_pos"] + self.center[1])),
            filter(lambda x: str(x["label_id"]) == self.resource_id, self.all_resource_point_list)
        )

    async def paste_resource(self, img: Image, pts: List[Tuple[int, int]]) -> Image:
        for x, y in pts:
            img.paste(
                self.resource_icon,
                (x + self.resource_icon_offset[0], y + self.resource_icon_offset[1]),
                self.resource_icon,
            )
        return img

    async def crop(self, img: Image, pts: List[Tuple[int, int]]) -> Image:
        for x, y in pts:
            self.x_start = min(x, self.x_start)
            self.y_start = min(y, self.y_start)
            self.x_end = max(x, self.x_end)
            self.y_end = max(y, self.y_end)

        self.x_start -= 150
        self.y_start -= 150
        self.x_end += 150
        self.y_end += 150
        if (self.x_end - self.x_start) < 1000:
            center = int((self.x_end + self.x_start) / 2)
            self.x_start = center - 500
            self.x_end = center + 500
        if (self.y_end - self.y_start) < 1000:
            center = int((self.y_end + self.y_start) / 2)
            self.y_start = center - 500
            self.y_end = center + 500

        return img.crop((self.x_start, self.y_start, self.x_end, self.y_end))

    @staticmethod
    async def toBytes(img: Image) -> bytes:
        bio = BytesIO()
        img.save(bio, format='JPEG')
        return bio.getvalue()

    async def _draw(self) -> Image:
        if self.map_cache[self.map_id]:
            self.center = self.map_cache[self.map_id]["center"]
            self.x_start, self.y_start = self.map_cache[self.map_id]["start"]
            resource_map = self.map_cache[self.map_id]["map"].copy()
        else:
            map_info = await self.get_map_info()
            resource_map = await self.create_map(map_info)
        resource_point_list = list(await self.get_resource_point_list())
        if resource_point_list:
            resource_map = await self.paste_resource(resource_map, resource_point_list)
            resource_map = await self.crop(resource_map, resource_point_list)
            return await self.toBytes(resource_map)
        else:
            raise Error("地图中该资源数目为0")

    @classmethod
    async def draw(cls, name: str, map_id: str = "2"):
        if not cls.downloader:
            cls.downloader = await Downloader.create()
        async with httpx.AsyncClient() as client:
            return await cls(client, name, map_id)._draw()

    @classmethod
    async def help(cls):
        if not cls.downloader:
            cls.downloader = await Downloader.create()
        return cls.downloader.help_list
