import re
from .util import ResourceMap, Error
from nonebot import on_regex
from nonebot.params import RegexDict
from nonebot.adapters.onebot.v11 import MessageSegment

where_resources = on_regex(r"#(?P<name>.+)?在(?P<map_name>.+)?哪")


@where_resources.handle()
async def _(res: dict = RegexDict()):
    if not res["name"]:
        await where_resources.finish("请指定物品！")

    if res["map_name"] in ["渊下宫"]:
        map_id = "7"
    elif res["map_name"] in ["层岩", "层岩巨渊"]:
        map_id = "9"
    elif res["map_name"] in ["海岛", "金苹果", "金苹果群岛"]:
        map_id = "12"
    else:
        map_id = "2"

    try:
        res = await ResourceMap.draw(res["name"], map_id)
        await where_resources.finish(MessageSegment.image(res))
    except Error as e:
        await where_resources.finish(str(e))
