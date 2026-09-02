"""检索评测语料：24 个跨模态素材 + 33 条查询（含库外反例）。

设计原则：
- 模态覆盖：图片 8 / 文档 6 / 视频 5 / 音频 5；
- 理解结果（描述/标签/转录）为确定性注入，保证评测可复现；
- 查询覆盖 关键词直配、标签检索、跨模态语义、库外反例四类。
"""
from __future__ import annotations

CORPUS: list[dict] = [
    # ---- 图片 ----
    {"name": "城市夜景.jpg", "modality": "image", "description": "夜晚城市摩天大楼灯光闪烁", "tags": ["夜景", "城市", "灯光"]},
    {"name": "海边日落.png", "modality": "image", "description": "海边日落晚霞洒在沙滩上", "tags": ["日落", "海边", "风景"]},
    {"name": "雪山风景.jpg", "modality": "image", "description": "雪山蓝天白云空气清新", "tags": ["雪山", "风景", "自然"]},
    {"name": "产品海报.png", "modality": "image", "description": "电子产品促销海报色彩鲜明", "tags": ["海报", "营销", "产品"]},
    {"name": "美食摄影.jpg", "modality": "image", "description": "美食摄影餐桌上的精致菜肴", "tags": ["美食", "摄影"]},
    {"name": "科技大楼.jpg", "modality": "image", "description": "现代玻璃幕墙科技大楼", "tags": ["建筑", "科技", "大楼"]},
    {"name": "复古游戏机.png", "modality": "image", "description": "复古像素游戏机界面", "tags": ["复古", "游戏", "像素"]},
    {"name": "人物肖像.jpg", "modality": "image", "description": "人物肖像摄影柔和光线", "tags": ["人像", "摄影"]},
    # ---- 文档 ----
    {"name": "营销方案.txt", "modality": "document", "description": "社交媒体推广内容种草直播带货", "tags": ["营销", "方案", "直播"], "text_content": "本季度营销方案聚焦社交媒体推广，通过内容种草、KOL合作与直播带货触达年轻用户。"},
    {"name": "论文摘要.txt", "modality": "document", "description": "深度学习多模态检索研究", "tags": ["学术", "论文", "深度学习"], "text_content": "本文研究深度学习在多模态检索中的应用，提出统一语义空间方法。"},
    {"name": "课程笔记.txt", "modality": "document", "description": "数据库原理与索引结构", "tags": ["学习", "笔记", "数据库"], "text_content": "数据库索引结构包括 B+ 树与哈希索引，覆盖查询优化。"},
    {"name": "招聘简章.txt", "modality": "document", "description": "招聘岗位要求与福利待遇", "tags": ["招聘", "求职", "岗位"], "text_content": "我们正在招聘后端工程师，要求熟悉 Python 与分布式系统。"},
    {"name": "健身计划.txt", "modality": "document", "description": "增肌训练计划与饮食建议", "tags": ["健身", "运动", "计划"], "text_content": "每周四次力量训练，配合高蛋白饮食。"},
    {"name": "旅游攻略.txt", "modality": "document", "description": "云南旅行攻略景点推荐", "tags": ["旅行", "攻略", "景点"], "text_content": "云南旅行攻略：大理、丽江、香格里拉必去景点。"},
    # ---- 视频 ----
    {"name": "产品发布会.mp4", "modality": "video", "description": "新品发布会舞台演讲", "tags": ["发布会", "产品", "科技"], "transcript": "我们正式发布新一代智能手表，续航提升百分之五十。"},
    {"name": "风景航拍.mp4", "modality": "video", "description": "无人机航拍山川河流", "tags": ["航拍", "风景", "自然"], "transcript": "俯瞰壮丽山河，云海翻涌。"},
    {"name": "游戏实况.mp4", "modality": "video", "description": "复古像素游戏实况解说", "tags": ["游戏", "实况", "复古"], "transcript": "今天我们玩这款复古像素游戏，挑战最高分。"},
    {"name": "舞蹈教学.mp4", "modality": "video", "description": "街舞教学分解动作", "tags": ["舞蹈", "教学", "健身"], "transcript": "跟着节奏，先学基础步伐，注意重心转移。"},
    {"name": "烹饪教程.mp4", "modality": "video", "description": "家常菜烹饪教程", "tags": ["美食", "教程", "烹饪"], "transcript": "先热锅再放油，大火快炒锁住水分。"},
    # ---- 音频 ----
    {"name": "播客访谈.mp3", "modality": "audio", "description": "科技播客嘉宾访谈", "tags": ["播客", "访谈", "科技"], "transcript": "我们聊聊人工智能的最新进展与落地挑战。"},
    {"name": "有声书.mp3", "modality": "audio", "description": "小说朗读有声书", "tags": ["有声书", "小说", "朗读"], "transcript": "他推开门，走进夜色中的城市。"},
    {"name": "白噪音.wav", "modality": "audio", "description": "雨声白噪音助眠", "tags": ["白噪音", "助眠", "雨声"]},
    {"name": "会议录音.mp3", "modality": "audio", "description": "团队周会录音", "tags": ["会议", "录音", "工作"], "transcript": "下个季度重点是增长与留存，同步产品迭代节奏。"},
    {"name": "歌曲.mp3", "modality": "audio", "description": "原创歌曲demo", "tags": ["音乐", "歌曲", "创作"], "transcript": "旋律轻快，副歌部分朗朗上口。"},
]

QUERIES: list[dict] = [
    # 关键词直配
    {"query": "夜景", "relevant": ["城市夜景.jpg"]},
    {"query": "城市灯光", "relevant": ["城市夜景.jpg"]},
    {"query": "日落", "relevant": ["海边日落.png"]},
    {"query": "雪山", "relevant": ["雪山风景.jpg"]},
    {"query": "产品海报", "relevant": ["产品海报.png"]},
    {"query": "美食", "relevant": ["美食摄影.jpg", "烹饪教程.mp4"]},
    {"query": "科技大楼", "relevant": ["科技大楼.jpg"]},
    {"query": "人像", "relevant": ["人物肖像.jpg"]},
    # 标签检索
    {"query": "复古游戏", "relevant": ["复古游戏机.png", "游戏实况.mp4"]},
    {"query": "像素游戏", "relevant": ["复古游戏机.png", "游戏实况.mp4"]},
    {"query": "营销方案", "relevant": ["营销方案.txt"]},
    {"query": "直播带货", "relevant": ["营销方案.txt"]},
    {"query": "求职招聘", "relevant": ["招聘简章.txt"]},
    {"query": "健身计划", "relevant": ["健身计划.txt"]},
    {"query": "云南旅游", "relevant": ["旅游攻略.txt"]},
    {"query": "助眠", "relevant": ["白噪音.wav"]},
    {"query": "会议", "relevant": ["会议录音.mp3"]},
    {"query": "音乐", "relevant": ["歌曲.mp3"]},
    # 跨模态 / 语义
    {"query": "智能手表", "relevant": ["产品发布会.mp4"]},
    {"query": "新品发布", "relevant": ["产品发布会.mp4"]},
    {"query": "航拍", "relevant": ["风景航拍.mp4"]},
    {"query": "游戏解说", "relevant": ["游戏实况.mp4"]},
    {"query": "街舞教学", "relevant": ["舞蹈教学.mp4"]},
    {"query": "烹饪教程", "relevant": ["烹饪教程.mp4"]},
    {"query": "科技播客", "relevant": ["播客访谈.mp3"]},
    {"query": "有声书", "relevant": ["有声书.mp3"]},
    {"query": "深度学习", "relevant": ["论文摘要.txt"]},
    {"query": "多模态检索", "relevant": ["论文摘要.txt"]},
    {"query": "数据库索引", "relevant": ["课程笔记.txt"]},
    # 语义换说法（与目标素材无表面词重叠，考验语义召回）
    {"query": "下雨天适合听什么", "relevant": ["白噪音.wav"]},
    {"query": "找工作看什么", "relevant": ["招聘简章.txt"]},
    {"query": "睡前放松的素材", "relevant": ["白噪音.wav", "有声书.mp3"]},
    {"query": "新手机宣传片", "relevant": ["产品发布会.mp4"]},
    {"query": "锻炼身体", "relevant": ["健身计划.txt", "舞蹈教学.mp4"]},
    {"query": "安静环境音", "relevant": ["白噪音.wav"]},
    {"query": "学做菜", "relevant": ["烹饪教程.mp4"]},
    {"query": "看跳舞", "relevant": ["舞蹈教学.mp4"]},
    # 库外反例（库中不应有相关素材）
    {"query": "量子物理", "relevant": []},
    {"query": "汽车报价", "relevant": []},
]

# ---------- 视觉评测扩展（深度二期） ----------

# 纯视觉查询：与素材描述/标签无表面词重叠，只有"看懂图片"才能命中
VISUAL_QUERIES: list[dict] = [
    {"query": "深蓝色夜空下高楼的剪影", "relevant": ["城市夜景.jpg"]},
    {"query": "橙色天空与深蓝海面的交界", "relevant": ["海边日落.png"]},
    {"query": "皑皑白雪覆盖的尖峰", "relevant": ["雪山风景.jpg"]},
    {"query": "镜面高楼在阳光下", "relevant": ["科技大楼.jpg"]},
    {"query": "红黄蓝绿的方块阵列", "relevant": ["复古游戏机.png"]},
    {"query": "暖色灯光下的食物近景", "relevant": ["美食摄影.jpg"]},
]

QUERIES = QUERIES + VISUAL_QUERIES


def _draw_night(p) -> None:
    import random

    from PIL import Image, ImageDraw

    rnd = random.Random(42)
    img = Image.new("RGB", (320, 240), (10, 15, 40))
    d = ImageDraw.Draw(img)
    for _ in range(8):
        x = rnd.randint(0, 280)
        w = rnd.randint(30, 70)
        h = rnd.randint(60, 180)
        d.rectangle([x, 240 - h, x + w, 240], fill=(20, 25, 55))
        for _ in range(rnd.randint(2, 5)):
            wx = x + rnd.randint(2, max(2, w - 6))
            wy = 240 - rnd.randint(5, h - 5)
            d.rectangle([wx, wy, wx + 3, wy + 3], fill=(255, 220, 90))
    img.save(p, "PNG")


def _draw_sunset(p) -> None:
    from PIL import Image, ImageDraw

    img = Image.new("RGB", (320, 240), (255, 120, 40))
    d = ImageDraw.Draw(img)
    for y in range(120):
        t = y / 120
        d.line([(0, y), (320, y)], fill=(int(255 - 60 * t), int(120 + 60 * t), int(40 + 120 * t)))
    d.ellipse([120, 30, 200, 110], fill=(255, 230, 150))
    d.rectangle([0, 120, 320, 240], fill=(40, 60, 110))
    for i in range(8):
        d.line([(0, 125 + i * 14), (320, 125 + i * 14)], fill=(90, 110, 160), width=2)
    img.save(p, "PNG")


def _draw_snow(p) -> None:
    from PIL import Image, ImageDraw

    img = Image.new("RGB", (320, 240), (135, 190, 230))
    d = ImageDraw.Draw(img)
    d.polygon([(30, 240), (160, 40), (290, 240)], fill=(250, 250, 255))
    d.polygon([(130, 240), (220, 90), (310, 240)], fill=(240, 245, 250))
    d.rectangle([0, 200, 320, 240], fill=(70, 120, 70))
    img.save(p, "PNG")


def _draw_poster(p) -> None:
    from PIL import Image, ImageDraw

    img = Image.new("RGB", (320, 240), (250, 240, 220))
    d = ImageDraw.Draw(img)
    d.rectangle([40, 60, 180, 190], fill=(60, 90, 200))
    d.rectangle([60, 90, 160, 130], fill=(230, 230, 235))
    d.rectangle([40, 200, 280, 220], fill=(220, 60, 60))
    img.save(p, "PNG")


def _draw_food(p) -> None:
    from PIL import Image, ImageDraw

    img = Image.new("RGB", (320, 240), (80, 50, 30))
    d = ImageDraw.Draw(img)
    d.ellipse([70, 50, 250, 190], fill=(230, 230, 220))
    d.ellipse([110, 90, 210, 160], fill=(180, 60, 40))
    d.ellipse([140, 110, 190, 145], fill=(240, 200, 120))
    for x, y in [(100, 80), (220, 120), (130, 170)]:
        d.ellipse([x, y, x + 20, y + 20], fill=(60, 120, 60))
    img.save(p, "PNG")


def _draw_tech(p) -> None:
    from PIL import Image, ImageDraw

    img = Image.new("RGB", (320, 240), (150, 170, 200))
    d = ImageDraw.Draw(img)
    d.rectangle([60, 30, 150, 240], fill=(70, 90, 120))
    d.rectangle([170, 70, 260, 240], fill=(90, 110, 140))
    for i in range(6):
        d.line([(70 + i * 13, 40), (70 + i * 13, 230)], fill=(140, 160, 190), width=3)
    d.rectangle([0, 210, 320, 240], fill=(40, 55, 75))
    img.save(p, "PNG")


def _draw_retro(p) -> None:
    import random

    from PIL import Image, ImageDraw

    rnd = random.Random(7)
    img = Image.new("RGB", (320, 240), (10, 10, 20))
    d = ImageDraw.Draw(img)
    colors = [(255, 60, 60), (255, 220, 60), (60, 220, 90), (60, 120, 255), (220, 90, 255)]
    for y in range(0, 240, 16):
        for x in range(0, 320, 16):
            if rnd.random() < 0.45:
                d.rectangle([x, y, x + 14, y + 14], fill=rnd.choice(colors))
    img.save(p, "PNG")


def _draw_portrait(p) -> None:
    from PIL import Image, ImageDraw

    img = Image.new("RGB", (320, 240), (220, 200, 180))
    d = ImageDraw.Draw(img)
    d.ellipse([110, 40, 210, 190], fill=(210, 170, 140))
    d.rectangle([90, 40, 230, 110], fill=(70, 50, 40))
    d.ellipse([140, 105, 160, 125], fill=(40, 30, 25))
    d.ellipse([175, 105, 195, 125], fill=(40, 30, 25))
    d.arc([135, 130, 190, 170], 20, 160, fill=(120, 60, 60), width=3)
    img.save(p, "PNG")


IMAGE_DRAWERS: dict[str, callable] = {
    "城市夜景.jpg": _draw_night,
    "海边日落.png": _draw_sunset,
    "雪山风景.jpg": _draw_snow,
    "产品海报.png": _draw_poster,
    "美食摄影.jpg": _draw_food,
    "科技大楼.jpg": _draw_tech,
    "复古游戏机.png": _draw_retro,
    "人物肖像.jpg": _draw_portrait,
}