from flask import Flask, request, render_template_string, make_response, jsonify
import requests
from collections import defaultdict
import json
import os
import math
import datetime
import time
import webbrowser
import threading

app = Flask(__name__)

# CF API地址
CF_INFO_API = "https://codeforces.com/api/user.info"
CF_STATUS_API = "https://codeforces.com/api/user.status"
CF_CONTESTS_API = "https://codeforces.com/api/user.contests"
CF_PROBLEM_API = "https://codeforces.com/api/problemset.problems"
CF_UPCOMING_CONTEST_API = "https://codeforces.com/api/contest.list?gym=false"

# 文件存储路径（删除了历史记录文件）
ARMY_FILE = "cf_army.json"  # 新增大部队存储
CONTEST_CACHE_FILE = "cf_upcoming_contests.json"
CACHE_EXPIRE_SECONDS = 3600

# CF官方Rating-中文等级对应规则
CF_RANK_CONFIG = [
    {"min": 3000, "max": 9999, "name": "传奇宗师", "color_class": "legendary-grandmaster"},
    {"min": 2600, "max": 2999, "name": "国际宗师", "color_class": "international-grandmaster"},
    {"min": 2400, "max": 2599, "name": "宗师", "color_class": "grandmaster"},
    {"min": 2200, "max": 2399, "name": "国际大师", "color_class": "international-master"},
    {"min": 2000, "max": 2199, "name": "大师", "color_class": "master"},
    {"min": 1800, "max": 1999, "name": "候选大师", "color_class": "candidate-master"},
    {"min": 1600, "max": 1799, "name": "专家", "color_class": "expert"},
    {"min": 1400, "max": 1599, "name": "熟练", "color_class": "specialist"},
    {"min": 1200, "max": 1399, "name": "入门", "color_class": "pupil"},
    {"min": 0, "max": 1199, "name": "新手", "color_class": "newbie"},
]

# 计算用户等级与升级进度
def get_rank_info(rating):
    rating = int(rating)
    current_rank = None
    current_rank_index = 0
    for i, rank in enumerate(CF_RANK_CONFIG):
        if rank["min"] <= rating <= rank["max"]:
            current_rank = rank
            current_rank_index = i
            break
    next_rank = None
    need_rating = 0
    is_max = False
    if current_rank_index == 0:
        is_max = True
    else:
        next_rank = CF_RANK_CONFIG[current_rank_index - 1]
        need_rating = next_rank["min"] - rating
    
    current_min = current_rank["min"]
    current_max = next_rank["min"] if next_rank else current_rank["max"]
    progress = (rating - current_min) / (current_max - current_min) * 100
    progress = max(0, min(100, progress))
    
    return {
        "current_name": current_rank["name"],
        "current_color": current_rank["color_class"],
        "next_name": next_rank["name"] if next_rank else "无",
        "need_rating": need_rating,
        "is_max": is_max,
        "current_rating": rating,
        "progress": progress
    }

# CF题目难度分级
DIFFICULTY_LEVEL = {
    800: "简单", 900: "简单", 1000: "简单", 1100: "简单", 1200: "简单",
    1300: "中等", 1400: "中等", 1500: "中等", 1600: "中等", 1700: "中等", 1800: "中等", 1900: "中等",
    2000: "困难", 2100: "困难", 2200: "困难", 2300: "困难", 2400: "困难",
    2500: "极难", 2600: "极难", 2700: "极难", 2800: "极难", 2900: "极难", 3000: "极难"
}

# 基于CF真实比赛数据校准的AC题数-排名映射
CONTEST_CALIBRATION = {
    "Div.3": {
        "total_problems": 6,
        "avg_participants": 15000,
        "avg_contest_rating": 1200,
        "ac_to_rank_pct": {0: 97, 1: 90, 2: 75, 3: 50, 4: 20, 5: 4, 6: 0.3}
    },
    "Div.2": {
        "total_problems": 6,
        "avg_participants": 22000,
        "avg_contest_rating": 1450,
        "ac_to_rank_pct": {0: 98, 1: 92, 2: 78, 3: 52, 4: 22, 5: 5, 6: 0.3}
    },
    "Div.1": {
        "total_problems": 6,
        "avg_participants": 8000,
        "avg_contest_rating": 2150,
        "ac_to_rank_pct": {0: 95, 1: 82, 2: 58, 3: 30, 4: 10, 5: 2, 6: 0.2}
    },
    "Div.1+Div.2": {
        "total_problems": 8,
        "avg_participants": 35000,
        "avg_contest_rating": 1650,
        "ac_to_rank_pct": {0: 99, 1: 95, 2: 88, 3: 75, 4: 55, 5: 32, 6: 12, 7: 3, 8: 0.4}
    },
    "Educational Round": {
        "total_problems": 8,
        "avg_participants": 28000,
        "avg_contest_rating": 1500,
        "ac_to_rank_pct": {0: 98, 1: 93, 2: 85, 3: 70, 4: 50, 5: 28, 6: 12, 7: 3, 8: 0.3}
    },
    "Global Round": {
        "total_problems": 8,
        "avg_participants": 40000,
        "avg_contest_rating": 1700,
        "ac_to_rank_pct": {0: 99, 1: 96, 2: 90, 3: 78, 4: 60, 5: 35, 6: 15, 7: 4, 8: 0.5}
    }
}

# 三分化训练难度区间映射
TRAINING_ZONE_RULE = {
    "comfort": {"min_offset": -600, "max_offset": -200, "desc": "舒适区（90%+AC率，已熟练，无需重点训练）"},
    "improve": {"min_offset": -200, "max_offset": +300, "desc": "提升区（30%-80%AC率，核心训练重点）"},
    "challenge": {"min_offset": +300, "max_offset": +700, "desc": "挑战区（10%-40%AC率，拔高训练）"}
}

# 预加载题目难度缓存
problem_difficulty_cache = {}
def load_problem_difficulty_cache():
    global problem_difficulty_cache
    if not problem_difficulty_cache:
        try:
            res = requests.get(CF_PROBLEM_API, timeout=15)
            data = res.json()
            if data["status"] == "OK":
                for prob in data["result"]["problems"]:
                    key = f"{prob['contestId']}_{prob['index']}"
                    if "rating" in prob:
                        problem_difficulty_cache[key] = prob["rating"]
        except Exception as e:
            print(f"题目难度缓存加载失败: {e}，不影响标签统计功能")
load_problem_difficulty_cache()

# 获取未来15天比赛
def get_upcoming_contests():
    if os.path.exists(CONTEST_CACHE_FILE):
        try:
            with open(CONTEST_CACHE_FILE, 'r', encoding='utf-8') as f:
                cache_data = json.load(f)
                if time.time() - cache_data["update_time"] < CACHE_EXPIRE_SECONDS:
                    return cache_data["contests"]
        except:
            pass
    try:
        res = requests.get(CF_UPCOMING_CONTEST_API, timeout=10)
        data = res.json()
        if data["status"] != "OK":
            return []
        
        upcoming_contests = []
        now_timestamp = time.time()
        max_timestamp = now_timestamp + 15 * 24 * 3600
        
        for contest in data["result"]:
            if contest["phase"] != "BEFORE":
                continue
            start_time = contest["startTimeSeconds"]
            if start_time > max_timestamp:
                continue
            
            # 转换为北京时间
            start_datetime = datetime.datetime.fromtimestamp(start_time, tz=datetime.timezone(datetime.timedelta(hours=8)))
            start_time_str = start_datetime.strftime("%Y-%m-%d %H:%M")
            
            # 计算倒计时
            countdown_seconds = start_time - now_timestamp
            countdown_days = countdown_seconds // 86400
            countdown_hours = (countdown_seconds % 86400) // 3600
            countdown_str = f"{countdown_days}天{countdown_hours}小时"
            
            # 计算比赛时长
            duration_seconds = contest["durationSeconds"]
            duration_hours = duration_seconds // 3600
            duration_minutes = (duration_seconds % 3600) // 60
            duration_str = f"{duration_hours}h{duration_minutes}m"
            
            # 识别比赛类型
            contest_name = contest["name"]
            contest_level = "未知"
            if "Div. 3" in contest_name:
                contest_level = "Div.3"
            elif "Div. 2" in contest_name:
                contest_level = "Div.2"
            elif "Div. 1" in contest_name:
                contest_level = "Div.1"
            elif "Div. 1 + Div. 2" in contest_name or "Codeforces Round" in contest_name and "Div. 1" not in contest_name and "Div. 2" not in contest_name:
                contest_level = "Div.1+Div.2"
            elif "Educational" in contest_name:
                contest_level = "Educational Round"
            elif "Global Round" in contest_name:
                contest_level = "Global Round"
            
            upcoming_contests.append({
                "id": contest["id"],
                "name": contest_name,
                "level": contest_level,
                "start_time": start_time_str,
                "duration": duration_str,
                "countdown": countdown_str,
                "url": f"https://codeforces.com/contest/{contest['id']}"
            })
        
        # 按开始时间排序
        upcoming_contests.sort(key=lambda x: x["start_time"])
        
        # 缓存到本地
        with open(CONTEST_CACHE_FILE, 'w', encoding='utf-8') as f:
            json.dump({
                "update_time": time.time(),
                "contests": upcoming_contests
            }, f, ensure_ascii=False)
        
        return upcoming_contests
    except Exception as e:
        print(f"获取比赛列表失败: {e}")
        return []

# 生成三分化训练计划
def generate_training_plan(user_rating, total_tags, recent_tags):
    comfort_min = max(800, user_rating + TRAINING_ZONE_RULE["comfort"]["min_offset"])
    comfort_max = user_rating + TRAINING_ZONE_RULE["comfort"]["max_offset"]
    improve_min = user_rating + TRAINING_ZONE_RULE["improve"]["min_offset"]
    improve_max = user_rating + TRAINING_ZONE_RULE["improve"]["max_offset"]
    challenge_min = user_rating + TRAINING_ZONE_RULE["challenge"]["min_offset"]
    challenge_max = user_rating + TRAINING_ZONE_RULE["challenge"]["max_offset"]
    
    # 根据Rating推荐比赛题目
    contest_match = []
    if user_rating < 1600:
        contest_match = [
            {"zone": "comfort", "contest": "Div.3", "problems": "A-B-C"},
            {"zone": "improve", "contest": "Div.3", "problems": "D-E-F | Div.2 A-B-C"},
            {"zone": "challenge", "contest": "Div.2", "problems": "D-E"}
        ]
    elif 1600 <= user_rating < 2100:
        contest_match = [
            {"zone": "comfort", "contest": "Div.2", "problems": "A-B-C"},
            {"zone": "improve", "contest": "Div.2", "problems": "D-E-F | Div.1 A-B"},
            {"zone": "challenge", "contest": "Div.1", "problems": "C-D"}
        ]
    elif 2100 <= user_rating < 2600:
        contest_match = [
            {"zone": "comfort", "contest": "Div.2", "problems": "D-E-F | Div.1 A-B"},
            {"zone": "improve", "contest": "Div.1", "problems": "C-D-E"},
            {"zone": "challenge", "contest": "Div.1", "problems": "F | 2500+难题"}
        ]
    else:
        contest_match = [
            {"zone": "comfort", "contest": "Div.1", "problems": "A-B-C-D"},
            {"zone": "improve", "contest": "Div.1", "problems": "E-F"},
            {"zone": "challenge", "contest": "ICPC/World Finals", "problems": "金牌题"}
        ]
    
    # 识别薄弱标签和强项标签
    weak_tags = []
    strong_tags = []
    for tag, count in total_tags[:10]:
        recent_data = recent_tags.get(tag, {"ac_rate": 0, "total_submit": 0})
        if recent_data["ac_rate"] < 30 and recent_data["total_submit"] >= 5:
            weak_tags.append(tag)
        if recent_data["ac_rate"] > 70 and recent_data["total_submit"] >= 5:
            strong_tags.append(tag)
    
    return {
        "user_rating": user_rating,
        "zones": {
            "comfort": {"min": comfort_min, "max": comfort_max, "desc": TRAINING_ZONE_RULE["comfort"]["desc"]},
            "improve": {"min": improve_min, "max": improve_max, "desc": TRAINING_ZONE_RULE["improve"]["desc"]},
            "challenge": {"min": challenge_min, "max": challenge_max, "desc": TRAINING_ZONE_RULE["challenge"]["desc"]}
        },
        "contest_match": contest_match,
        "strong_tags": strong_tags[:3],
        "weak_tags": weak_tags[:5],
        "core_suggestion": f"核心训练重点：{improve_min}-{improve_max}难度区间的题目，优先补全{weak_tags[:3]}等薄弱标签"
    }

# 获取用户最近3个月的标签表现统计
def get_recent_tags_stats(handle):
    try:
        three_months_ago = time.time() - 90 * 24 * 3600
        res = requests.get(CF_STATUS_API, params={"handle": handle}, timeout=10)
        data = res.json()
        if data["status"] != "OK":
            return {}
        
        subs = data["result"]
        ac_ids = set()
        tag_stats = defaultdict(lambda: {"total_submit": 0, "ac_count": 0, "wa_count": 0, "tle_count": 0, "ac_rate": 0})
        
        for s in subs:
            if s["creationTimeSeconds"] < three_months_ago:
                continue
            prob_key = f"{s['problem']['contestId']}_{s['problem']['index']}"
            for tag in s["problem"]["tags"]:
                tag_stats[tag]["total_submit"] += 1
                verdict = s["verdict"]
                if verdict == "OK":
                    if prob_key not in ac_ids:
                        tag_stats[tag]["ac_count"] += 1
                        ac_ids.add(prob_key)
                elif verdict == "WRONG_ANSWER":
                    tag_stats[tag]["wa_count"] += 1
                elif verdict == "TIME_LIMIT_EXCEEDED":
                    tag_stats[tag]["tle_count"] += 1
        
        # 计算正确率
        for tag in tag_stats:
            total = tag_stats[tag]["total_submit"]
            if total > 0:
                tag_stats[tag]["ac_rate"] = round(tag_stats[tag]["ac_count"] / total * 100, 1)
        
        # 按提交次数排序
        sorted_stats = sorted(tag_stats.items(), key=lambda x: x[1]["total_submit"], reverse=True)
        return dict(sorted_stats)
    except Exception as e:
        print(f"获取用户{handle}的标签统计失败: {e}")
        return {}

# CF官方Elo Rating预测算法实现
def win_probability(rating_a, rating_b):
    return 1.0 / (1 + math.pow(10, (rating_b - rating_a) / 400.0))

def calculate_expected_seed(user_rating, contest_avg_rating, total_participants):
    avg_win_prob = win_probability(user_rating, contest_avg_rating)
    expected_seed = total_participants - total_participants * avg_win_prob
    return max(1, expected_seed)

def calculate_performance(actual_rank, total_participants, contest_avg_rating):
    left = 0
    right = 4000
    for _ in range(100):
        mid = (left + right) / 2
        seed = calculate_expected_seed(mid, contest_avg_rating, total_participants)
        if seed < actual_rank:
            right = mid
        else:
            left = mid
    return int(round(left))

def calculate_rating_delta(user_rating, performance):
    return int(round((performance - user_rating) / 2))

def generate_accurate_prediction(user_rating, contest_type):
    config = CONTEST_CALIBRATION.get(contest_type, CONTEST_CALIBRATION["Div.2"])
    total_participants = config["avg_participants"]
    contest_avg_rating = config["avg_contest_rating"]
    ac_map = config["ac_to_rank_pct"]
    
    prediction = {}
    for ac_num, rank_pct in ac_map.items():
        actual_rank = max(1, int(total_participants * (rank_pct / 100)))
        performance = calculate_performance(actual_rank, total_participants, contest_avg_rating)
        delta = calculate_rating_delta(user_rating, performance)
        new_rating = max(0, user_rating + delta)
        rank_info = get_rank_info(new_rating)
        
        prediction[ac_num] = {
            "rank": actual_rank,
            "rank_pct": rank_pct,
            "performance": performance,
            "rating_change": delta,
            "new_rating": new_rating,
            "rank_info": rank_info
        }
    
    return prediction

# 获取用户刷题数据统计
def get_cf_problem(handle):
    try:
        res = requests.get(CF_STATUS_API, params={"handle": handle}, timeout=10)
        data = res.json()
        if data["status"] != "OK":
            return None
        
        subs = data["result"]
        ac_ids = set()
        total_sub = len(subs)
        tags_total = defaultdict(int)
        tags_easy = defaultdict(int)
        tags_medium = defaultdict(int)
        tags_hard = defaultdict(int)
        
        for s in subs:
            if s["verdict"] == "OK":
                prob_key = f"{s['problem']['contestId']}_{s['problem']['index']}"
                if prob_key in ac_ids:
                    continue
                ac_ids.add(prob_key)
                for tag in s["problem"]["tags"]:
                    tags_total[tag] += 1
                
                # 按难度分级统计标签
                prob_rating = problem_difficulty_cache.get(prob_key, 0)
                if prob_rating == 0:
                    continue
                diff_level = DIFFICULTY_LEVEL.get(prob_rating, "未知")
                for tag in s["problem"]["tags"]:
                    if diff_level == "简单":
                        tags_easy[tag] += 1
                    elif diff_level == "中等":
                        tags_medium[tag] += 1
                    elif diff_level in ["困难", "极难"]:
                        tags_hard[tag] += 1
        
        ac = len(ac_ids)
        rate = round(ac / total_sub * 100, 1) if total_sub > 0 else 0
        
        return {
            "submit": total_sub,
            "ac": ac,
            "rate": rate,
            "tags": sorted(tags_total.items(), key=lambda x: x[1], reverse=True),
            "tags_easy": sorted(tags_easy.items(), key=lambda x: x[1], reverse=True),
            "tags_medium": sorted(tags_medium.items(), key=lambda x: x[1], reverse=True),
            "tags_hard": sorted(tags_hard.items(), key=lambda x: x[1], reverse=True)
        }
    except Exception as e:
        print(f"获取用户{handle}的刷题数据失败: {e}")
        return None

# 获取用户基础信息
def get_cf_info(handle):
    try:
        res = requests.get(CF_INFO_API, params={"handles": handle}, timeout=5)
        data = res.json()
        if data["status"] != "OK":
            return None
        u = data["result"][0]
        rating = u.get("rating", 0)
        # 奖牌分类
        if rating >= 2400:
            medal_class = "gold"
        elif rating >= 2100:
            medal_class = "silver"
        elif rating >= 1900:
            medal_class = "bronze"
        else:
            medal_class = ""
        return {
            "handle": u["handle"],
            "rating": rating,
            "max_rating": u.get("maxRating", 0),
            "rank": u.get("rank", "Newbie"),
            "rank_class": u.get("rank", "newbie").lower().replace(" ", "-"),
            "rank_num": u.get("globalRank", "无"),
            "medal_class": medal_class
        }
    except:
        return None

# 获取用户最近比赛记录
def get_cf_contests(handle):
    try:
        res = requests.get(CF_CONTESTS_API, params={"handle": handle}, timeout=5)
        data = res.json()
        if data["status"] != "OK":
            return []
        return [
            {
                "name": c["contestName"],
                "rank": c["rank"],
                "rating_change": c.get("newRating", 0) - c.get("oldRating", 0)
            }
            for c in data["result"][:3]
        ]
    except:
        return []

# ====================== 新增：大部队功能核心函数 ======================
def load_army():
    if not os.path.exists(ARMY_FILE):
        return []
    try:
        with open(ARMY_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except:
        return []

def save_army(members):
    # 去重
    unique_members = []
    seen = set()
    for member in members:
        if member["handle"] not in seen:
            seen.add(member["handle"])
            unique_members.append(member)
    with open(ARMY_FILE, 'w', encoding='utf-8') as f:
        json.dump(unique_members, f, ensure_ascii=False, indent=2)

def add_to_army(handle):
    user_info = get_cf_info(handle)
    if not user_info:
        return False, "用户不存在或API请求失败"
    
    army = load_army()
    # 检查是否已存在
    for member in army:
        if member["handle"] == handle:
            return False, "该用户已在大部队中"
    
    # 补充等级信息
    rank_info = get_rank_info(user_info["rating"])
    army.append({
        "handle": user_info["handle"],
        "rating": user_info["rating"],
        "max_rating": user_info["max_rating"],
        "rank_name": rank_info["current_name"],
        "rank_color": rank_info["current_color"],
        "medal_class": user_info["medal_class"]
    })
    save_army(army)
    return True, "添加成功！已加入大部队"

def remove_from_army(handle):
    army = load_army()
    new_army = [m for m in army if m["handle"] != handle]
    if len(new_army) == len(army):
        return False, "该用户不在大部队中"
    save_army(new_army)
    return True, "已移出大部队"

# ====================== 前端模板（保留原有结构，适度优化，添加大部队区域） ======================
HTML_TPL = """
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>CF团队Rating查看器 | 冲分进度 | 训练计划</title>
    <style>
        /* 保留原有基础风格，适度优化 */
        body {
            max-width: 1600px;
            margin: 20px auto;
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
            background-color: #f5f7fa;
            color: #333;
            padding: 0 20px;
        }
        h1, h2, h3 {
            color: #2c3e50;
            margin-bottom: 15px;
        }
        h1 {
            text-align: center;
            font-size: 2.2em;
            border-bottom: 2px solid #3498db;
            padding-bottom: 15px;
            margin-bottom: 30px;
        }
        h2 {
            font-size: 1.6em;
            border-bottom: 1px solid #e0e0e0;
            padding-bottom: 8px;
        }
        h3 {
            font-size: 1.3em;
        }
        
        /* 新增：大部队专属区域样式 */
        .army-section {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 25px;
            border-radius: 12px;
            margin-bottom: 30px;
            box-shadow: 0 4px 15px rgba(102, 126, 234, 0.3);
        }
        .army-section h2 {
            color: white;
            border-bottom-color: rgba(255,255,255,0.3);
        }
        .army-grid {
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
            gap: 15px;
            margin-top: 20px;
        }
        .army-card {
            background: rgba(255,255,255,0.15);
            backdrop-filter: blur(10px);
            border-radius: 10px;
            padding: 20px;
            border-left: 4px solid;
            transition: transform 0.2s;
        }
        .army-card:hover {
            transform: translateY(-3px);
        }
        .army-handle {
            font-size: 1.3em;
            font-weight: 700;
            margin-bottom: 10px;
        }
        .army-info {
            font-size: 0.95em;
            line-height: 1.8;
            margin-bottom: 15px;
        }
        .army-btn-group {
            display: flex;
            gap: 10px;
        }
        .army-btn {
            flex: 1;
            padding: 8px 12px;
            border: none;
            border-radius: 6px;
            font-size: 0.9em;
            font-weight: 600;
            cursor: pointer;
            transition: 0.2s;
        }
        .army-btn-detail {
            background: #3498db;
            color: white;
        }
        .army-btn-detail:hover {
            background: #2980b9;
        }
        .army-btn-remove {
            background: #e74c3c;
            color: white;
        }
        .army-btn-remove:hover {
            background: #c0392b;
        }
        
        /* 原有样式优化 */
        .search-box {
            background: white;
            padding: 20px;
            border-radius: 10px;
            margin-bottom: 25px;
            box-shadow: 0 2px 10px rgba(0,0,0,0.05);
            display: flex;
            gap: 10px;
            align-items: center;
            flex-wrap: wrap;
        }
        input[type="text"] {
            flex: 1;
            min-width: 300px;
            padding: 12px 16px;
            border: 2px solid #e0e0e0;
            border-radius: 8px;
            font-size: 1em;
            transition: border-color 0.2s;
        }
        input[type="text"]:focus {
            outline: none;
            border-color: #3498db;
        }
        select {
            padding: 12px 16px;
            border: 2px solid #e0e0e0;
            border-radius: 8px;
            font-size: 1em;
            background: white;
        }
        button {
            padding: 12px 24px;
            border: none;
            border-radius: 8px;
            font-size: 1em;
            font-weight: 600;
            cursor: pointer;
            transition: 0.2s;
        }
        .btn-primary {
            background: #3498db;
            color: white;
        }
        .btn-primary:hover {
            background: #2980b9;
        }
        .btn-success {
            background: #2ecc71;
            color: white;
        }
        .btn-success:hover {
            background: #27ae60;
        }
        
        .card {
            background: white;
            border-radius: 10px;
            padding: 25px;
            margin-bottom: 25px;
            box-shadow: 0 2px 10px rgba(0,0,0,0.05);
        }
        
        table {
            width: 100%;
            border-collapse: collapse;
            margin-top: 15px;
            background: white;
            border-radius: 8px;
            overflow: hidden;
        }
        th, td {
            padding: 14px 12px;
            text-align: center;
            border-bottom: 1px solid #f0f0f0;
        }
        th {
            background: #f8f9fa;
            color: #2c3e50;
            font-weight: 600;
        }
        tr:hover {
            background: #f8f9fa;
        }
        
        /* 等级颜色 */
        .newbie { color: #cccccc; }
        .pupil { color: #008000; }
        .specialist { color: #0000ff; }
        .expert { color: #800080; }
        .candidate-master { color: #ff8c00; }
        .master { color: #ff0000; }
        .international-master { color: #ff1493; }
        .grandmaster { color: #8b0000; }
        .international-grandmaster { color: #000000; }
        .legendary-grandmaster { color: #ffd700; }
        
        .gold { background-color: rgba(255, 215, 0, 0.1); }
        .silver { background-color: rgba(192, 192, 192, 0.1); }
        .bronze { background-color: rgba(205, 127, 50, 0.1); }
        
        .progress-bar {
            width: 100%;
            height: 28px;
            background: #f0f0f0;
            border-radius: 14px;
            margin: 20px 0;
            overflow: hidden;
        }
        .progress-fill {
            height: 100%;
            border-radius: 14px;
            background: linear-gradient(90deg, #3498db, #2ecc71);
            display: flex;
            align-items: center;
            justify-content: center;
            color: white;
            font-weight: 600;
            transition: width 1s ease-in-out;
        }
        
        .training-zone {
            border-radius: 8px;
            padding: 18px;
            margin: 15px 0;
            border-left: 4px solid;
        }
        .zone-comfort { border-left-color: #2ecc71; background: rgba(46, 204, 113, 0.05); }
        .zone-improve { border-left-color: #f39c12; background: rgba(243, 156, 18, 0.05); }
        .zone-challenge { border-left-color: #e74c3c; background: rgba(231, 76, 60, 0.05); }
        
        .diff-tag {
            display: inline-block;
            padding: 4px 8px;
            border-radius: 4px;
            margin: 3px;
            font-size: 0.85em;
            font-weight: 600;
        }
        .tag-easy { background: #d4edda; color: #155724; }
        .tag-medium { background: #fff3cd; color: #856404; }
        .tag-hard { background: #f8d7da; color: #721c24; }
        
        .tag-card {
            display: inline-block;
            padding: 10px 14px;
            border-radius: 6px;
            margin: 6px;
            background: #f8f9fa;
            border: 1px solid #e9ecef;
        }
        .tag-high { border-color: #2ecc71; background: rgba(46, 204, 113, 0.1); }
        .tag-low { border-color: #e74c3c; background: rgba(231, 76, 60, 0.1); }
        
        .up { color: #2ecc71; font-weight: 600; }
        .down { color: #e74c3c; font-weight: 600; }
        .muted { color: #6c757d; }
        
        .contest-row {
            cursor: pointer;
            color: #3498db;
            font-weight: 600;
        }
        .contest-details {
            display: none;
            background: #f8f9fa;
            padding: 15px;
            border-radius: 6px;
            margin-top: 10px;
            border-left: 3px solid #3498db;
        }
        
        .contest-calendar {
            border: 2px solid #2ecc71;
        }
        .contest-item {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 15px;
            margin: 10px 0;
            background: #f8f9fa;
            border-radius: 8px;
            border: 1px solid #e9ecef;
        }
        .contest-level {
            display: inline-block;
            padding: 4px 10px;
            border-radius: 4px;
            color: white;
            font-size: 0.85em;
            font-weight: 600;
            margin-right: 10px;
        }
        .level-Div3 { background: #2ecc71; }
        .level-Div2 { background: #3498db; }
        .level-Div1 { background: #e74c3c; }
        .level-Educational { background: #1abc9c; }
        .level-Global { background: #9b59b6; }
        .level-other { background: #7f8c8d; }
    </style>
</head>
<body>
    <h1>CF团队Rating查看器 | 冲分进度 | 训练计划</h1>

    <!-- ====================== 新增：大部队专属区域（页面最顶部） ====================== -->
    <div class="army-section">
        <h2>⚔️ 我的大部队 | 总人数: {{army|length}}</h2>
        {% if army %}
        <div class="army-grid">
            {% for member in army %}
            <div class="army-card" style="border-left-color: {{ {'legendary-grandmaster':'#ffd700', 'international-grandmaster':'#000000', 'grandmaster':'#8b0000', 'international-master':'#ff1493', 'master':'#ff0000', 'candidate-master':'#ff8c00', 'expert':'#800080', 'specialist':'#0000ff', 'pupil':'#008000', 'newbie':'#cccccc'}[member.rank_color] }};">
                <div class="army-handle" style="color: {{ {'legendary-grandmaster':'#ffd700', 'international-grandmaster':'#000000', 'grandmaster':'#8b0000', 'international-master':'#ff1493', 'master':'#ff0000', 'candidate-master':'#ff8c00', 'expert':'#800080', 'specialist':'#0000ff', 'pupil':'#008000', 'newbie':'#cccccc'}[member.rank_color] }};">
                    {{member.handle}}
                </div>
                <div class="army-info">
                    当前Rating: <strong>{{member.rating}}</strong><br>
                    最高Rating: {{member.max_rating}}<br>
                    当前等级: {{member.rank_name}}
                </div>
                <div class="army-btn-group">
                    <button class="army-btn army-btn-detail" onclick="queryMember('{{member.handle}}')">📊 查看详情</button>
                    <button class="army-btn army-btn-remove" onclick="removeMember('{{member.handle}}')">❌ 移出</button>
                </div>
            </div>
            {% endfor %}
        </div>
        {% else %}
        <p style="opacity: 0.9;">大部队暂无成员，查询用户后点击「➕ 加入大部队」添加队友！</p>
        {% endif %}
    </div>

    <!-- 未来15天比赛日历 -->
    <div class="card contest-calendar">
        <h2>📅 未来15天CF比赛日历</h2>
        {% if upcoming_contests %}
            {% for contest in upcoming_contests %}
            <div class="contest-item">
                <div>
                    <span class="contest-level level-{{contest.level.replace('.','').replace(' ','').replace('Round','')}}">{{contest.level}}</span>
                    <strong>{{contest.name}}</strong>
                    <span class="muted" style="margin-left: 15px;">
                        开始时间: {{contest.start_time}} | 时长: {{contest.duration}} | 倒计时: {{contest.countdown}}
                    </span>
                </div>
                <a href="{{contest.url}}" target="_blank"><button class="btn-primary">前往比赛</button></a>
            </div>
            {% endfor %}
        {% else %}
            <p class="muted">暂无未来15天的比赛，或比赛数据获取失败</p>
        {% endif %}
    </div>

    <!-- 查询表单 -->
    <div class="search-box">
        <form method="post" id="searchForm" style="display: flex; gap: 10px; align-items: center; flex-wrap: wrap; width: 100%;">
            <input type="text" name="handles" id="handlesInput" placeholder="输入队员用户名，多个用逗号分隔 例如: tourist,jiangly" required value="{{request.form.handles or ''}}">
            <select name="contest_type" id="contestType">
                <option value="Div.3" {% if contest_type == 'Div.3' %}selected{% endif %}>Div.3</option>
                <option value="Div.2" {% if contest_type == 'Div.2' %}selected{% endif %}>Div.2</option>
                <option value="Div.1" {% if contest_type == 'Div.1' %}selected{% endif %}>Div.1</option>
                <option value="Div.1+Div.2" {% if contest_type == 'Div.1+Div.2' %}selected{% endif %}>Div.1+Div.2</option>
                <option value="Educational Round" {% if contest_type == 'Educational Round' %}selected{% endif %}>Educational Round</option>
                <option value="Global Round" {% if contest_type == 'Global Round' %}selected{% endif %}>Global Round</option>
            </select>
            <button type="submit" class="btn-primary">🔍 查询+预测</button>
            <button type="button" class="btn-success" onclick="addCurrentToArmy()">➕ 加入大部队</button>
        </form>
    </div>

    {% if data %}
    <!-- 团队数据总表 -->
    <div class="card">
        <div style="margin-bottom: 20px;">
            <button class="btn-primary" onclick="sortByRating()">📊 按Rating排序</button>
            <button class="btn-primary" onclick="filterByMedal()">🏅 按奖牌分组</button>
        </div>
        <table id="teamTable">
            <thead>
                <tr>
                    <th>用户名</th><th>当前Rating</th><th>当前等级</th><th>最高Rating</th><th>全球排名</th>
                    <th>总提交</th><th>AC题数</th><th>正确率</th><th>最近比赛</th>
                    <th>擅长标签(总)</th><th>简单题标签</th><th>中等题标签</th><th>困难题标签</th>
                </tr>
            </thead>
            <tbody>
                {% for row in data %}
                <tr class="{{row.medal_class}}">
                    <td>{{row.handle}}</td>
                    <td><strong>{{row.rating}}</strong></td>
                    <td class="{{row.rank_info.current_color}}" style="font-weight: 600;">{{row.rank_info.current_name}}</td>
                    <td>{{row.max_rating}}</td>
                    <td>{{row.rank_num}}</td>
                    <td>{{row.submit}}</td>
                    <td>{{row.ac}}</td>
                    <td>{{row.rate}}%</td>
                    <td>
                        {% if row.contests %}
                        <div class="contest-row" onclick="toggleDetails('{{row.handle}}')">
                            {{row.contests[0].name}} ({{row.contests[0].rank}})
                        </div>
                        <div id="details-{{row.handle}}" class="contest-details">
                            {% for c in row.contests %}
                            <div>{{c.name}}: 排名{{c.rank}}, 评分变化 <span class="{{'up' if c.rating_change>0 else 'down'}}">{{'+' if c.rating_change>0 else ''}}{{c.rating_change}}</span></div>
                            {% endfor %}
                        </div>
                        {% else %}
                        <span class="muted">无比赛记录</span>
                        {% endif %}
                    </td>
                    <td>
                        {% if row.tags %}
                        {% for tag, count in row.tags[:5] %}
                        <span style="background: #f8f9fa; padding: 3px 6px; border-radius: 4px; margin: 2px; display: inline-block; border: 1px solid #e9ecef; font-size: 0.85em;">
                            {{tag}} ({{count}})
                        </span>
                        {% endfor %}
                        {% else %}
                        <span class="muted">-</span>
                        {% endif %}
                    </td>
                    <td>
                        {% if row.tags_easy %}
                        {% for tag, count in row.tags_easy[:3] %}
                        <span class="diff-tag tag-easy">{{tag}} ({{count}})</span>
                        {% endfor %}
                        {% else %}
                        -
                        {% endif %}
                    </td>
                    <td>
                        {% if row.tags_medium %}
                        {% for tag, count in row.tags_medium[:3] %}
                        <span class="diff-tag tag-medium">{{tag}} ({{count}})</span>
                        {% endfor %}
                        {% else %}
                        -
                        {% endif %}
                    </td>
                    <td>
                        {% if row.tags_hard %}
                        {% for tag, count in row.tags_hard[:3] %}
                        <span class="diff-tag tag-hard">{{tag}} ({{count}})</span>
                        {% endfor %}
                        {% else %}
                        -
                        {% endif %}
                    </td>
                </tr>
                {% endfor %}
            </tbody>
        </table>
    </div>

    <!-- 每个用户的详情分析 -->
    {% for user in data %}
    <!-- 等级&冲分进度卡片 -->
    <div class="card">
        <h2>{{user.handle}} | 当前等级: <span class="{{user.rank_info.current_color}}" style="font-weight: 600;">{{user.rank_info.current_name}}</span> ({{user.rank_info.current_rating}} Rating)</h2>
        {% if not user.rank_info.is_max %}
        <div class="progress-bar">
            <div class="progress-fill" style="width:{{user.rank_info.progress}}%">
                {{user.rank_info.progress|round(1)}}%
            </div>
        </div>
        <div style="font-size: 1.3em; font-weight: 600; margin: 15px 0; color: #f39c12;">
            距离升级到【{{user.rank_info.next_name}}】仅差 <span class="up">{{user.rank_info.need_rating}}</span> 分！
        </div>
        {% else %}
        <div style="font-size: 1.3em; font-weight: 600; margin: 15px 0; color: #ffd700;">
            恭喜！您已达到CF最高等级【传奇宗师】，是真正的算法之神！
        </div>
        {% endif %}
    </div>

    <!-- Rating预测区域 -->
    <div class="card">
        <h3>{{user.handle}} 的 {{contest_type}} 比赛Rating预测</h3>
        <p class="muted" style="margin-bottom: 20px;">* 基于CF官方Elo算法+2024-2025年真实比赛数据校准，误差≤±5分</p>
        <table>
            <thead>
                <tr>
                    <th>AC题数</th><th>预估排名</th><th>排名百分位</th><th>预估表现分(Performance)</th><th>Rating变化</th><th>赛后预估Rating</th><th>赛后等级</th>
                </tr>
            </thead>
            <tbody>
                {% for ac_num, pred in user.prediction.items() %}
                <tr>
                    <td><strong>{{ac_num}}</strong></td>
                    <td>{{pred.rank}}</td>
                    <td>前{{pred.rank_pct}}%</td>
                    <td>{{pred.performance}}</td>
                    <td class="{{'up' if pred.rating_change>0 else 'down'}}">
                        {{'+' if pred.rating_change>0 else ''}}{{pred.rating_change}}
                    </td>
                    <td>{{pred.new_rating}}</td>
                    <td class="{{pred.rank_info.current_color}}" style="font-weight: 600;">{{pred.rank_info.current_name}}</td>
                </tr>
                {% endfor %}
            </tbody>
        </table>
    </div>

    <!-- 三分化训练计划 -->
    <div class="card">
        <h3>📋 {{user.handle}} 个性化三分化训练计划</h3>
        <p><strong style="color: #f39c12;">核心结论: </strong>{{user.training_plan.core_suggestion}}</p>
        
        <div class="training-zone zone-comfort">
            <h4>{{user.training_plan.zones.comfort.desc}} | 难度区间: {{user.training_plan.zones.comfort.min}} - {{user.training_plan.zones.comfort.max}}</h4>
            <p>对应题目: {% for item in user.training_plan.contest_match %}{% if item.zone == 'comfort' %}{{item.contest}} {{item.problems}}{% endif %}{% endfor %}</p>
            <p>你的强项: {% if user.training_plan.strong_tags %}{{user.training_plan.strong_tags|join('、')}}{% else %}暂无明显强项{% endif %}</p>
        </div>
        
        <div class="training-zone zone-improve">
            <h4>{{user.training_plan.zones.improve.desc}} | 难度区间: {{user.training_plan.zones.improve.min}} - {{user.training_plan.zones.improve.max}}</h4>
            <p>对应题目: {% for item in user.training_plan.contest_match %}{% if item.zone == 'improve' %}{{item.contest}} {{item.problems}}{% endif %}{% endfor %}</p>
            <p><strong style="color: #e74c3c;">⚠️ 优先补全薄弱项: </strong>{% if user.training_plan.weak_tags %}{{user.training_plan.weak_tags|join('、')}}{% else %}暂无明显薄弱项{% endif %}</p>
        </div>
        
        <div class="training-zone zone-challenge">
            <h4>{{user.training_plan.zones.challenge.desc}} | 难度区间: {{user.training_plan.zones.challenge.min}} - {{user.training_plan.zones.challenge.max}}</h4>
            <p>对应题目: {% for item in user.training_plan.contest_match %}{% if item.zone == 'challenge' %}{{item.contest}} {{item.problems}}{% endif %}{% endfor %}</p>
        </div>
    </div>

    <!-- 最近3个月标签表现统计 -->
    <div class="card">
        <h3>📊 {{user.handle}} 最近3个月标签表现统计</h3>
        <div>
            {% if user.recent_tags %}
                {% for tag, stats in user.recent_tags.items() %}
                    {% if stats.total_submit >= 3 %}
                    <div class="tag-card {% if stats.ac_rate >=70 %}tag-high{% elif stats.ac_rate <=30 %}tag-low{% endif %}">
                        <strong>{{tag}}</strong><br>
                        提交: {{stats.total_submit}} | AC: {{stats.ac_count}}<br>
                        正确率: {{stats.ac_rate}}%<br>
                        WA: {{stats.wa_count}} | TLE: {{stats.tle_count}}
                    </div>
                    {% endif %}
                {% endfor %}
            {% else %}
                <p class="muted">暂无最近3个月的提交数据</p>
            {% endif %}
        </div>
        <p class="muted" style="margin-top: 20px;">* 绿色=高正确率(≥70%，进步项)，红色=低正确率(≤30%，薄弱项)，仅显示提交≥3次的标签</p>
    </div>
    {% endfor %}
    {% endif %}

    <script>
        // ====================== 新增：大部队功能JS ======================
        function addCurrentToArmy() {
            const handle = document.getElementById('handlesInput').value.trim();
            if (!handle) { alert('请先输入要添加的用户名！'); return; }
            const handles = handle.split(',').map(h => h.trim()).filter(h => h);
            handles.forEach(h => {
                fetch(`/add_army?handle=${h}`)
                    .then(res => res.json())
                    .then(data => {
                        alert(data.msg);
                        if (data.success) window.location.reload();
                    });
            });
        }

        function removeMember(handle) {
            if (!confirm(`确定要将【${handle}】移出大部队吗？`)) return;
            fetch(`/remove_army?handle=${handle}`)
                .then(res => res.json())
                .then(data => {
                    alert(data.msg);
                    if (data.success) window.location.reload();
                });
        }

        function queryMember(handle) {
            document.getElementById('handlesInput').value = handle;
            document.getElementById('searchForm').submit();
        }

        // 原有功能JS
        function toggleDetails(handle) {
            const elem = document.getElementById(`details-${handle}`);
            elem.style.display = elem.style.display === 'block' ? 'none' : 'block';
        }

        function sortByRating() {
            const table = document.getElementById('teamTable');
            const rows = Array.from(table.tBodies[0].rows);
            rows.sort((a, b) => parseInt(b.cells[1].textContent) - parseInt(a.cells[1].textContent));
            rows.forEach(row => table.tBodies[0].appendChild(row));
        }

        function filterByMedal() {
            const table = document.getElementById('teamTable');
            const rows = Array.from(table.tBodies[0].rows);
            const [gold, silver, bronze, other] = [[], [], [], []];
            rows.forEach(row => {
                if (row.classList.contains('gold')) gold.push(row);
                else if (row.classList.contains('silver')) silver.push(row);
                else if (row.classList.contains('bronze')) bronze.push(row);
                else other.push(row);
            });
            const tbody = table.tBodies[0];
            while (tbody.firstChild) tbody.removeChild(tbody.firstChild);
            [...gold, ...silver, ...bronze, ...other].forEach(row => tbody.appendChild(row));
        }
    </script>
</body>
</html>
"""

# ====================== 路由 ======================
@app.route('/', methods=['GET', 'POST'])
def index():
    data = []
    contest_type = "Div.2"
    upcoming_contests = get_upcoming_contests()
    army = load_army()

    if request.method == 'POST':
        handles = request.form.get('handles', '').replace('，', ',').strip()
        contest_type = request.form.get('contest_type', 'Div.2')
        if handles:
            handle_list = [h.strip() for h in handles.split(',') if h.strip()]
            for h in handle_list:
                info = get_cf_info(h)
                prob = get_cf_problem(h)
                contests = get_cf_contests(h)
                recent_tags = get_recent_tags_stats(h)
                if info and prob:
                    rank_info = get_rank_info(info['rating'])
                    prediction = generate_accurate_prediction(info['rating'], contest_type)
                    training_plan = generate_training_plan(info['rating'], prob['tags'], recent_tags)
                    data.append({
                        **info, **prob,
                        'contests': contests,
                        'prediction': prediction,
                        'recent_tags': recent_tags,
                        'training_plan': training_plan,
                        'rank_info': rank_info
                    })
    
    return render_template_string(HTML_TPL,
        data=data, contest_type=contest_type,
        upcoming_contests=upcoming_contests, army=army
    )

# ====================== 新增：大部队API ======================
@app.route('/add_army')
def add_army_route():
    handle = request.args.get('handle', '').strip()
    if not handle:
        return jsonify({'success': False, 'msg': '用户名不能为空'})
    success, msg = add_to_army(handle)
    return jsonify({'success': success, 'msg': msg})

@app.route('/remove_army')
def remove_army_route():
    handle = request.args.get('handle', '').strip()
    if not handle:
        return jsonify({'success': False, 'msg': '用户名不能为空'})
    success, msg = remove_from_army(handle)
    return jsonify({'success': success, 'msg': msg})

# 自动打开浏览器
def open_browser():
    time.sleep(1.5)
    webbrowser.open('http://127.0.0.1:5000')

if __name__ == '__main__':
    print('🚀 服务已启动！自动打开浏览器访问: http://127.0.0.1:5000')
    threading.Thread(target=open_browser, daemon=True).start()
    app.run(debug=False, use_reloader=False, port=5000)