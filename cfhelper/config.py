# -*- coding: utf-8 -*-
"""集中配置：所有常量、等级表、难度分档、比赛校准数据。

这里只放纯数据，不依赖 Flask / requests，方便单独测试与复用。
"""

APP_VERSION = "2.16"

# ==================== CF API 端点 ====================
CF_API_BASE      = "https://codeforces.com/api"
CF_INFO_API      = f"{CF_API_BASE}/user.info"
CF_STATUS_API    = f"{CF_API_BASE}/user.status"
CF_RATING_API    = f"{CF_API_BASE}/user.rating"        # 正确的比赛/Rating历史端点（旧版误用 user.contests）
CF_PROBLEM_API   = f"{CF_API_BASE}/problemset.problems"
CF_CONTESTS_API  = f"{CF_API_BASE}/contest.list?gym=false"
CF_CONTEST_LIST_API = f"{CF_API_BASE}/contest.list"    # gym 由参数控制，供 ICPC 比赛库使用

# 统一请求超时（秒）与轻量重试
HTTP_TIMEOUT = 12
HTTP_RETRY   = 2
# 全局并发 CF 请求上限：CF 对匿名接口有反爬限流，并发过高会被判 "Call limit exceeded"，
# 这里用信号量把同时在飞的请求压到这个数，既加速又不触发封禁。
HTTP_MAX_CONCURRENCY = 4
# 用户数据（info/status/rating）进程内缓存秒数：重复查询 / army 点详情直接命中，免重拉。
USER_CACHE_TTL = 300
# 缓存条目数上限。每个用户占 3 条（info/subs/rating），其中 subs 存的是完整提交记录，
# 重量级账号有上万条——只判过期不淘汰的话，查得越多内存涨得越多且永不释放。30 条 ≈ 10 个用户。
USER_CACHE_MAX = 30

# ==================== 运行参数 ====================
CONTEST_CACHE_FILE   = "cf_upcoming_contests.json"
ICPC_CACHE_FILE      = "cf_icpc_contests.json"   # ICPC 比赛库缓存
ICPC_CACHE_SECONDS   = 7 * 86400   # 历年赛事几乎不变，缓存一周；新赛季可在页面上手动刷新
ICPC_PROBLEMS_FILE   = "cf_icpc_problems.json"   # 各场比赛的题号列表：历史赛事不变，永久缓存
API_KEY_FILE         = "cf_api.json"             # 可选的 CF API 密钥（访问 Gym 题单用）
# 抓题单时每场之间的间隔秒数。实测串行连打 1.47s/场不触发限流，留一点余量更稳。
ICPC_FETCH_DELAY     = 0.3
# 抽取比赛时的「已吃透」线：解出比例高于此值的场次不再被抽到（练它的边际收益太低）。
ICPC_PICK_SKIP_RATE  = 60

# ==================== 奖牌线（几题能拿冠军 / 金 / 银 / 铜） ====================
# 缓存里存的是**解题数分布**而不是算好的金银铜线：奖牌比例是可能调整的，
# 存了分布，改比例就能就地重算，不必重新拉 160 场榜单（那要 10 分钟）。
ICPC_MEDALS_FILE     = "cf_icpc_medals.json"
# 榜单要拉的行数。CF Gym 榜单里绝大多数是赛后练习的人，真实赛场队伍（ghost）混在其中，
# 必须拉够深才能把他们取全——实测南京 2024 共 3136 行，其中赛场队伍 359 支。
ICPC_STANDINGS_ROWS  = 5000
# 单场榜单可达 3MB，默认 12 秒超时不够用
ICPC_STANDINGS_TIMEOUT = 60
# 奖牌线靠名次推（CF 没有奖牌信息）。两套规则不能混用：
# 一般赛事（区域赛 / 省赛 / EC-Final）按**名次百分位**，累计口径
# ——前 30% 是"银牌及以上"，含金牌区。
ICPC_MEDAL_PCT       = {"gold": 10, "silver": 30, "bronze": 60}
# World Finals 是**固定名次**：前 4 金、5-10 银、11-20 铜。
# 同样记累计上界（银 = 10 名以内，铜 = 20 名以内），与保底题数的算法口径一致。
ICPC_MEDAL_WF_RANKS  = {"gold": 4, "silver": 10, "bronze": 20}
ARMY_FILE            = "cf_army.json"
TODO_FILE            = "cf_todo.json"           # 题单/待做收藏（跨会话保留）
CACHE_EXPIRE_SECONDS = 3600          # 比赛列表缓存有效期
UPCOMING_DAYS        = 30            # 未来比赛展示窗口（更新想法：看未来一个月）
RECENT_DAYS          = 90            # 近况标签统计窗口
HEATMAP_DAYS         = 365           # 刷题热力图回看天数（约一年）
# 心跳超时（秒）后自动退出进程。
# 为什么是 5 分钟而不是 30 秒：浏览器会给后台标签页的定时器降频——Chrome 在标签隐藏
# 约 5 分钟后启用 intensive throttling，把 setInterval 压到**每分钟一次**，系统休眠时
# 更是完全冻结。心跳本身是 5 秒一次，降频后必然超过 30 秒，于是"页面明明开着，
# 进程却自杀了"，用户再点任何东西都是"找不到"。
# 放宽几乎没有代价：正常关页走的是 sendBeacon，2~4 秒就退出（见 SHUTDOWN_GRACE），
# 这个超时只是信标失效（浏览器崩溃 / 被拦）时的兜底。
HEARTBEAT_TIMEOUT    = 300
SHUTDOWN_GRACE       = 2             # 收到 /shutdown 后的宽限秒数：留给应用内跳转的新页面来心跳

# 训练计划薄弱/强项判定阈值（基于近况正确率）
WEAK_AC_RATE   = 40    # 正确率低于此值视为薄弱
STRONG_AC_RATE = 75    # 正确率高于此值视为强项
MIN_RECENT_PROBLEMS = 3  # 至少尝试这么多道题，统计才有意义

# 推荐题目数量
RECOMMEND_LIMIT = 8

# CF 题库真实难度分范围（实测 11006 道带分题恰好落在 800~3500）。
# 注意别拿 DIFFICULTY_BANDS 最高档的 max=9999 当上限——那只是分档区间的开口，不是真有题。
MIN_PROBLEM_RATING = 800
MAX_PROBLEM_RATING = 3500
# 未评级用户（CF 不返回 rating 字段，上游填 0）的训练计划基准分。
# 0 不代表"比 800 还弱"，直接套区间偏移会算出 800 ~ -200 的倒挂区间、推荐题恒为空。
UNRATED_PLAN_RATING = 1200

# ==================== 弱点墙：按难度档算真实通过率，定位能力天花板 ====================
# 单阈值设计：可信档中通过率 ≥ WALL_WALL_RATE 的最高一档 = 稳固上限；
# 其上第一个可信档 = 墙（它的通过率必然 < WALL_WALL_RATE，否则它自己就成上限了）。
WALL_MIN_ATTEMPTS = 4    # 某档至少尝试这么多题，通过率才算可信（上限与墙都受此约束）
WALL_WALL_RATE    = 50   # 稳固上限与「墙」的共同分界线

# ==================== 刷题器：从全站题库按条件出题 ====================
PICK_DEFAULT_COUNT = 12
PICK_MAX_COUNT     = 50

# ==================== 团队作战板 ====================
TEAM_MAX_SIZE      = 6   # 一次最多分析几人（ICPC 是 3 人，留点余量）
TEAM_MATRIX_TAGS   = 16  # 技能矩阵展示多少个标签（按全队解题总数取 TOP）
TEAM_WEAK_BEST_MAX = 4   # 某标签连全队最强者解题数都 < 此值 → 判为全队共同弱项

# ==================== CF 官方 Rating → 中文等级 ====================
# 颜色采用 CF 官方配色（specialist 青、expert 蓝、CM 紫、master 橙、GM 红）
CF_RANK_CONFIG = [
    {"min": 3000, "max": 9999, "name": "传奇宗师", "color_class": "legendary-grandmaster"},
    {"min": 2600, "max": 2999, "name": "国际宗师", "color_class": "international-grandmaster"},
    {"min": 2400, "max": 2599, "name": "宗师",     "color_class": "grandmaster"},
    {"min": 2200, "max": 2399, "name": "国际大师", "color_class": "international-master"},
    {"min": 2000, "max": 2199, "name": "大师",     "color_class": "master"},
    {"min": 1800, "max": 1999, "name": "候选大师", "color_class": "candidate-master"},
    {"min": 1600, "max": 1799, "name": "专家",     "color_class": "expert"},
    {"min": 1400, "max": 1599, "name": "熟练",     "color_class": "specialist"},
    {"min": 1200, "max": 1399, "name": "入门",     "color_class": "pupil"},
    {"min":    0, "max": 1199, "name": "新手",     "color_class": "newbie"},
]

# 等级颜色（供后端拼装、前端共享）
RANK_COLORS = {
    "legendary-grandmaster":    "#ff0000",
    "international-grandmaster": "#ff0000",
    "grandmaster":              "#ff0000",
    "international-master":      "#ff8c00",
    "master":                   "#ff8c00",
    "candidate-master":         "#aa00aa",
    "expert":                   "#0000ff",
    "specialist":               "#03a89e",
    "pupil":                    "#008000",
    "newbie":                   "#808080",
}

# ==================== 精细化 11 级难度分档 ====================
DIFFICULTY_BANDS = [
    {"min": 3000, "max": 9999, "name": "神级",   "cls": "d-legend", "desc": "≥3000"},
    {"min": 2700, "max": 2999, "name": "大师级", "cls": "d-master", "desc": "2700-2999"},
    {"min": 2400, "max": 2699, "name": "宗师级", "cls": "d-gm",     "desc": "2400-2699"},
    {"min": 2100, "max": 2399, "name": "专家+",  "cls": "d-exp2",   "desc": "2100-2399"},
    {"min": 1900, "max": 2099, "name": "提升级", "cls": "d-hard2",  "desc": "1900-2099"},
    {"min": 1700, "max": 1899, "name": "进阶级", "cls": "d-hard1",  "desc": "1700-1899"},
    {"min": 1500, "max": 1699, "name": "中等+",  "cls": "d-med2",   "desc": "1500-1699"},
    {"min": 1300, "max": 1499, "name": "中等",   "cls": "d-med1",   "desc": "1300-1499"},
    {"min": 1100, "max": 1299, "name": "简单+",  "cls": "d-easy2",  "desc": "1100-1299"},
    {"min":  900, "max": 1099, "name": "简单",   "cls": "d-easy1",  "desc": "900-1099"},
    {"min":    0, "max":  899, "name": "入门",   "cls": "d-intro",  "desc": "≤800"},
]

# 四大粗分桶（团队总表用）
SIMPLE_LEVELS = ["简单", "中等", "困难", "极难"]


def simple_level(rating: int) -> str:
    if rating <= 1099:
        return "简单"
    if rating <= 1699:
        return "中等"
    if rating <= 2099:
        return "困难"
    return "极难"


# ==================== 比赛 Rating 预测校准 ====================
# ac_to_rank_pct: AC 题数 → 名次百分位（基于历史真实数据估算）
CONTEST_CALIBRATION = {
    "Div.4": {
        "total_problems": 8, "avg_participants": 25000, "avg_contest_rating": 1100,
        "ac_to_rank_pct": {0: 96, 1: 88, 2: 70, 3: 48, 4: 25, 5: 10, 6: 3, 7: 0.8, 8: 0.2},
    },
    "Div.3": {
        "total_problems": 7, "avg_participants": 18000, "avg_contest_rating": 1200,
        "ac_to_rank_pct": {0: 97, 1: 90, 2: 75, 3: 50, 4: 25, 5: 9, 6: 2, 7: 0.3},
    },
    "Div.2": {
        "total_problems": 6, "avg_participants": 22000, "avg_contest_rating": 1450,
        "ac_to_rank_pct": {0: 98, 1: 92, 2: 78, 3: 52, 4: 22, 5: 5, 6: 0.3},
    },
    "Div.1": {
        "total_problems": 6, "avg_participants": 8000, "avg_contest_rating": 2150,
        "ac_to_rank_pct": {0: 95, 1: 82, 2: 58, 3: 30, 4: 10, 5: 2, 6: 0.2},
    },
    "Div.1+Div.2": {
        "total_problems": 8, "avg_participants": 35000, "avg_contest_rating": 1650,
        "ac_to_rank_pct": {0: 99, 1: 95, 2: 88, 3: 75, 4: 55, 5: 32, 6: 12, 7: 3, 8: 0.4},
    },
    "Educational Round": {
        "total_problems": 8, "avg_participants": 28000, "avg_contest_rating": 1500,
        "ac_to_rank_pct": {0: 98, 1: 93, 2: 85, 3: 70, 4: 50, 5: 28, 6: 12, 7: 3, 8: 0.3},
    },
    "Global Round": {
        "total_problems": 8, "avg_participants": 40000, "avg_contest_rating": 1700,
        "ac_to_rank_pct": {0: 99, 1: 96, 2: 90, 3: 78, 4: 60, 5: 35, 6: 15, 7: 4, 8: 0.5},
    },
}

# 预测下拉框可选项
CONTEST_TYPES = ["Div.4", "Div.3", "Div.2", "Div.1", "Div.1+Div.2",
                 "Educational Round", "Global Round"]

# ==================== 三分化训练区间 ====================
TRAINING_ZONE_RULE = {
    "comfort":   {"min_offset": -600, "max_offset": -200,
                  "desc": "舒适区（AC率90%+，已熟练，维持手感）"},
    "improve":   {"min_offset": -200, "max_offset": +300,
                  "desc": "提升区（AC率30%-80%，核心训练重点）"},
    "challenge": {"min_offset": +300, "max_offset": +700,
                  "desc": "挑战区（AC率10%-40%，拔高训练）"},
}

# ==================== 比赛日历：等级样式 & 推荐匹配 ====================
# 日历里识别出的 level 关键字 → CSS class
CONTEST_LEVEL_CLASS = {
    "Div.4": "lv-Div4", "Div.3": "lv-Div3", "Div.2": "lv-Div2",
    "Div.1": "lv-Div1", "Div.1+Div.2": "lv-Div1Div2",
    "Educational": "lv-Educational", "Global": "lv-Global", "其他": "lv-other",
}


def recommended_levels(rating: int):
    """根据 rating 给出"适合参加"的比赛 level 集合（用于日历高亮）。"""
    if rating < 1400:
        return {"Div.4", "Div.3", "Div.2"}
    if rating < 1900:
        return {"Div.2", "Educational", "Div.1+Div.2"}
    if rating < 2100:
        return {"Div.2", "Educational", "Div.1+Div.2", "Global"}
    return {"Div.1", "Div.1+Div.2", "Global"}
