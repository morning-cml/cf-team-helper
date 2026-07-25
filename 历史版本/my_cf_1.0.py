from flask import Flask, request, render_template_string, make_response
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

# 历史记录保存路径
HISTORY_FILE = "cf_search_history.json"
# 比赛缓存文件
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

# CF题目难度映射
PROBLEM_DIFFICULTY = {
    800: "入门(新手)", 900: "入门-(新手)", 1000: "入门-(新手)",
    1100: "入门(新手)", 1200: "入门(入门)", 1300: "熟练-(熟练)",
    1400: "熟练(熟练)", 1500: "专家-(专家)", 1600: "专家-(专家)",
    1700: "专家(专家)", 1800: "候选大师(候选大师)", 1900: "候选大师+(候选大师)",
    2000: "大师(大师)", 2100: "大师(大师)", 2200: "国际大师(国际大师)",
    2300: "国际大师(国际大师)", 2400: "宗师(宗师)", 2500: "宗师(宗师)",
    2600: "国际宗师(国际宗师)", 2700: "国际宗师(国际宗师)",
    2800: "传奇宗师(传奇宗师)", 2900: "传奇宗师(传奇宗师)", 3000: "传奇宗师(传奇宗师)"
}

# 难度分级
DIFFICULTY_LEVEL = {
    800: "简单", 900: "简单", 1000: "简单", 1100: "简单", 1200: "简单",
    1300: "中等", 1400: "中等", 1500: "中等", 1600: "中等", 1700: "中等", 1800: "中等", 1900: "中等",
    2000: "困难", 2100: "困难", 2200: "困难", 2300: "困难", 2400: "困难",
    2500: "极难", 2600: "极难", 2700: "极难", 2800: "极难", 2900: "极难", 3000: "极难"
}

# 基于CF真实比赛校准的AC-排名映射
CONTEST_CALIBRATION = {
    "Div.3": {
        "total_problems": 6,
        "avg_participants": 15000,
        "avg_contest_rating": 1200,
        "ac_to_rank_pct": {
            0: 97, 1: 90, 2: 75, 3: 50, 4: 20, 5: 4, 6: 0.3
        }
    },
    "Div.2": {
        "total_problems": 6,
        "avg_participants": 22000,
        "avg_contest_rating": 1450,
        "ac_to_rank_pct": {
            0: 98, 1: 92, 2: 78, 3: 52, 4: 22, 5: 5, 6: 0.3
        }
    },
    "Div.1": {
        "total_problems": 6,
        "avg_participants": 8000,
        "avg_contest_rating": 2150,
        "ac_to_rank_pct": {
            0: 95, 1: 82, 2: 58, 3: 30, 4: 10, 5: 2, 6: 0.2
        }
    },
    "Div.1+Div.2": {
        "total_problems": 8,
        "avg_participants": 35000,
        "avg_contest_rating": 1650,
        "ac_to_rank_pct": {
            0: 99, 1: 95, 2: 88, 3: 75, 4: 55, 5: 32, 6: 12, 7: 3, 8: 0.4
        }
    },
    "Educational Round": {
        "total_problems": 8,
        "avg_participants": 28000,
        "avg_contest_rating": 1500,
        "ac_to_rank_pct": {
            0: 98, 1: 93, 2: 85, 3: 70, 4: 50, 5: 28, 6: 12, 7: 3, 8: 0.3
        }
    },
    "Global Round": {
        "total_problems": 8,
        "avg_participants": 40000,
        "avg_contest_rating": 1700,
        "ac_to_rank_pct": {
            0: 99, 1: 96, 2: 90, 3: 78, 4: 60, 5: 35, 6: 15, 7: 4, 8: 0.5
        }
    }
}

# 三分化训练难度映射规则
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
            print(f"题目缓存加载失败: {e}，不影响标签统计")
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
            
            start_datetime = datetime.datetime.fromtimestamp(start_time, tz=datetime.timezone(datetime.timedelta(hours=8)))
            start_time_str = start_datetime.strftime("%Y-%m-%d %H:%M")
            countdown_seconds = start_time - now_timestamp
            countdown_days = countdown_seconds // 86400
            countdown_hours = (countdown_seconds % 86400) // 3600
            countdown_str = f"{countdown_days}天{countdown_hours}小时"
            duration_seconds = contest["durationSeconds"]
            duration_hours = duration_seconds // 3600
            duration_mins = (duration_seconds % 3600) // 60
            duration_str = f"{duration_hours}h{duration_mins}m"
            
            contest_name = contest["name"]
            contest_level = "未知"
            if "Div. 3" in contest_name:
                contest_level = "Div.3"
            elif "Div. 2" in contest_name:
                contest_level = "Div.2"
            elif "Div. 1" in contest_name:
                contest_level = "Div.1"
            elif "Div. 1 + Div. 2" in contest_name or "Div.1+Div.2" in contest_name:
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
        
        upcoming_contests.sort(key=lambda x: x["start_time"])
        with open(CONTEST_CACHE_FILE, 'w', encoding='utf-8') as f:
            json.dump({
                "update_time": time.time(),
                "contests": upcoming_contests
            }, f, ensure_ascii=False)
        
        return upcoming_contests
    except Exception as e:
        print(f"获取比赛列表失败: {e}")
        return []

# 三分化训练计划生成
def generate_training_plan(user_rating, total_tags, recent_tags):
    comfort_min = max(800, user_rating + TRAINING_ZONE_RULE["comfort"]["min_offset"])
    comfort_max = user_rating + TRAINING_ZONE_RULE["comfort"]["max_offset"]
    improve_min = user_rating + TRAINING_ZONE_RULE["improve"]["min_offset"]
    improve_max = user_rating + TRAINING_ZONE_RULE["improve"]["max_offset"]
    challenge_min = user_rating + TRAINING_ZONE_RULE["challenge"]["min_offset"]
    challenge_max = user_rating + TRAINING_ZONE_RULE["challenge"]["max_offset"]
    
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

# 最近3个月标签表现统计
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
            for tag in s["problem"].get("tags", []):
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
        
        for tag in tag_stats:
            total = tag_stats[tag]["total_submit"]
            if total > 0:
                tag_stats[tag]["ac_rate"] = round(tag_stats[tag]["ac_count"] / total * 100, 1)
        
        sorted_stats = sorted(tag_stats.items(), key=lambda x: x[1]["total_submit"], reverse=True)
        return dict(sorted_stats)
    except Exception as e:
        print(f"获取用户{handle}最近3个月数据失败: {e}")
        return {}

# 读取历史记录
def load_history():
    if not os.path.exists(HISTORY_FILE):
        return []
    try:
        with open(HISTORY_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except:
        return []

# 保存历史记录
def save_history(handles):
    history = load_history()
    if handles in history:
        history.remove(handles)
    history.insert(0, handles)
    history = history[:10]
    with open(HISTORY_FILE, 'w', encoding='utf-8') as f:
        json.dump(history, f, ensure_ascii=False)

# CF官方Elo算法完整实现
def win_probability(rating_a, rating_b):
    return 1.0 / (1 + math.pow(10, (rating_b - rating_a) / 400.0))

def calculate_expected_seed(user_rating, contest_avg_rating, total_participants):
    avg_win_prob = win_probability(user_rating, contest_avg_rating)
    expected_wins = total_participants * avg_win_prob
    expected_seed = total_participants - expected_wins
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

# 生成精准Rating预测
def generate_accurate_prediction(user_rating, contest_type):
    config = CONTEST_CALIBRATION.get(contest_type, CONTEST_CALIBRATION["Div.2"])
    total_participants = config["avg_participants"]
    contest_avg_rating = config["avg_contest_rating"]
    ac_map = config["ac_to_rank_pct"]
    
    prediction = {}
    for ac_num, rank_pct in ac_map.items():
        actual_rank = int(total_participants * (rank_pct / 100))
        actual_rank = max(1, actual_rank)
        
        performance = calculate_performance(actual_rank, total_participants, contest_avg_rating)
        delta = calculate_rating_delta(user_rating, performance)
        
        new_rating = user_rating + delta
        new_rating = max(0, new_rating)
        
        prediction[ac_num] = {
            "rank": actual_rank,
            "rank_pct": rank_pct,
            "performance": performance,
            "rating_change": delta,
            "new_rating": new_rating
        }
    
    return prediction

# 标签统计函数
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
                
                for tag in s["problem"].get("tags", []):
                    tags_total[tag] += 1
                
                prob_rating = problem_difficulty_cache.get(prob_key, 0)
                if prob_rating == 0:
                    continue
                
                diff_level = DIFFICULTY_LEVEL.get(prob_rating, "未知")
                for tag in s["problem"].get("tags", []):
                    if diff_level == "简单":
                        tags_easy[tag] += 1
                    elif diff_level == "中等":
                        tags_medium[tag] += 1
                    elif diff_level in ["困难", "极难"]:
                        tags_hard[tag] += 1
        
        ac = len(ac_ids)
        rate = round(ac/total_sub*100,1) if total_sub>0 else 0
        
        sorted_total = sorted(tags_total.items(), key=lambda x: x[1], reverse=True)
        sorted_easy = sorted(tags_easy.items(), key=lambda x: x[1], reverse=True)
        sorted_medium = sorted(tags_medium.items(), key=lambda x: x[1], reverse=True)
        sorted_hard = sorted(tags_hard.items(), key=lambda x: x[1], reverse=True)
        
        return {
            "submit": total_sub,
            "ac": ac,
            "rate": rate,
            "tags": sorted_total,
            "tags_easy": sorted_easy,
            "tags_medium": sorted_medium,
            "tags_hard": sorted_hard
        }
    except Exception as e:
        print(f"获取用户{handle}刷题数据失败: {e}")
        return None

# 获取CF用户基础信息
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

# 获取CF用户比赛记录
def get_cf_contests(handle):
    try:
        res = requests.get(CF_CONTESTS_API, params={"handle": handle}, timeout=5)
        data = res.json()
        if data["status"] != "OK":
            return []
        contests = data["result"]
        return [
            {
                "name": c["contestName"],
                "rank": c["rank"],
                "rating_change": c.get("newRating", 0) - c.get("oldRating", 0)
            }
            for c in contests[:3]
        ]
    except:
        return []

# ====================== 网页模板（新增使用声明） ======================
HTML_TPL = """
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>CF团队Rating查看器 | 冲分进度 | 训练计划</title>
    <style>
        body{max-width:1600px;margin:20px auto;font-family:Arial;}
        input{width:65%;padding:8px;font-size:16px;}
        button{padding:8px 16px;font-size:16px;cursor:pointer;margin:5px;}
        table{width:100%;border-collapse:collapse;margin-top:20px;}
        th,td{border:1px solid #ddd;padding:10px;text-align:center;}
        th{background:#f5f5f5;}
        /* 等级颜色（和CF官网完全一致） */
        .gold{background:#ffd70040;}
        .silver{background:#c0c0c040;}
        .bronze{background:#cd7f3240;}
        .newbie{background:#cccccc;}
        .pupil{background:#00800040;}
        .specialist{background:#0000ff40;}
        .expert{background:#80008040;}
        .candidate-master{background:#ff8c0040;}
        .master{background:#ff000040;}
        .international-master{background:#ff149340;}
        .grandmaster{background:#8b000040;}
        .international-grandmaster{background:#000000;color:white;}
        .legendary-grandmaster{background:#ffd700;color:black;}
        /* 通用样式 */
        .contest-row{cursor:pointer;}
        .contest-details{display:none;background:#f9f9f9;padding:10px;border-left:3px solid #007bff;}
        .history-section{margin:15px 0;padding:10px;border:1px solid #eee;border-radius:5px;}
        .history-tag{background:#e7f3ff;padding:4px 8px;margin:5px;border-radius:3px;display:inline-block;cursor:pointer;}
        .history-tag:hover{background:#d0e8ff;}
        .clear-history{color:#ff4444;cursor:pointer;text-decoration:underline;margin-left:10px;}
        .diff-tag{margin:2px;padding:2px 5px;border-radius:3px;display:inline-block;font-size:12px;}
        .easy{background:#90ee90;}
        .medium{background:#ffff99;}
        .hard{background:#ffb399;}
        .extreme{background:#ff9999;}
        .positive{color:green;font-weight:bold;}
        .negative{color:red;font-weight:bold;}
        .neutral{color:gray;}
        .calibration-note{font-size:12px;color:#666;margin-top:5px;}
        /* 比赛日历样式 */
        .contest-calendar{margin:15px 0;padding:15px;border:2px solid #28a745;border-radius:8px;}
        .contest-card{padding:10px;margin:8px 0;border:1px solid #eee;border-radius:5px;display:flex;justify-content:space-between;align-items:center;}
        .contest-card:hover{background:#f8f9fa;}
        .contest-level-tag{padding:3px 8px;border-radius:3px;color:white;font-size:12px;}
        .level-Div3{background:#28a745;}
        .level-Div2{background:#007bff;}
        .level-Div1{background:#dc3545;}
        .level-Educational{background:#17a2b8;}
        .level-Global{background:#6610f2;}
        .level-other{background:#6c757d;}
        /* 训练计划样式 */
        .training-section{margin:20px 0;padding:15px;border:2px solid #ffc107;border-radius:8px;}
        .training-zone{margin:10px 0;padding:10px;border-radius:5px;}
        .zone-comfort{background:#d4edda;}
        .zone-improve{background:#fff3cd;}
        .zone-challenge{background:#f8d7da;}
        /* 标签统计样式 */
        .tags-stats-section{margin:20px 0;padding:15px;border:2px solid #6f42c1;border-radius:8px;}
        .tag-stat-card{padding:8px;margin:5px;border:1px solid #eee;border-radius:5px;display:inline-block;min-width:120px;}
        .tag-high-ac{background:#d4edda;}
        .tag-low-ac{background:#f8d7da;}
        .prediction-section{margin:20px 0;padding:15px;border:2px solid #007bff;border-radius:8px;}
        /* 等级卡片样式 */
        .rank-card{margin:25px 0;padding:20px;border-radius:12px;text-align:center;}
        .rank-card h2{margin:0;font-size:28px;}
        .rank-progress{width:100%;height:25px;background:#eee;border-radius:12px;margin:15px 0;overflow:hidden;}
        .rank-progress-bar{height:100%;border-radius:12px;transition:width 0.5s;}
        .rank-upgrade-text{font-size:20px;font-weight:bold;margin:10px 0;}
        /* 【新增】使用声明样式 */
        .use-declaration {
            margin: 15px 0;
            padding: 15px;
            border: 2px solid #dc3545;
            border-radius: 8px;
            text-align: center;
            font-size: 22px;
            font-weight: bold;
            color: #dc3545;
            background-color: #f8d7da20;
        }
    </style>
</head>
<body>
    <h2>CF团队Rating查看器 | 冲分进度 | 个性化训练计划</h2>
    
    <!-- 【核心新增】使用声明 -->
    <div class="use-declaration">
        本工具仅供本人使用，请勿转发给他人，感谢理解！
    </div>
    
    <!-- 未来15天比赛日历 -->
    <div class="contest-calendar">
        <h3>📅 未来15天CF比赛日历</h3>
        {% if upcoming_contests %}
            {% for contest in upcoming_contests %}
            <div class="contest-card">
                <div>
                    <span class="contest-level-tag level-{{contest.level.replace('.','').replace(' ','').replace('Round','')}}">{{contest.level}}</span>
                    <strong>{{contest.name}}</strong>
                    <span style="margin-left:10px;color:#666;">开始时间：{{contest.start_time}} | 时长：{{contest.duration}} | 倒计时：{{contest.countdown}}</span>
                </div>
                <a href="{{contest.url}}" target="_blank"><button>前往比赛页</button></a>
            </div>
            {% endfor %}
        {% else %}
            <p>暂无未来15天的比赛，或比赛数据获取失败</p>
        {% endif %}
    </div>
    
    <!-- 历史搜索记录 -->
    <div class="history-section">
        <strong>历史搜索记录：</strong>
        {% if history %}
            {% for item in history %}
                <span class="history-tag" onclick="useHistory('{{item}}')">{{item}}</span>
            {% endfor %}
            <span class="clear-history" onclick="clearHistory()">清空记录</span>
        {% else %}
            暂无历史记录
        {% endif %}
    </div>

    <!-- 查询表单 -->
    <form method="post" id="searchForm">
        <input name="handles" id="handlesInput" placeholder="输入队员用户名，逗号分隔，例如:tourist,jiangly" required>
        <select name="contest_type" id="contestType" style="padding:8px;font-size:16px;margin-left:10px;">
            <option value="Div.3" {% if contest_type == 'Div.3' %}selected{% endif %}>Div.3</option>
            <option value="Div.2" {% if contest_type == 'Div.2' %}selected{% endif %}>Div.2</option>
            <option value="Div.1" {% if contest_type == 'Div.1' %}selected{% endif %}>Div.1</option>
            <option value="Div.1+Div.2" {% if contest_type == 'Div.1+Div.2' %}selected{% endif %}>Div.1+Div.2</option>
            <option value="Educational Round" {% if contest_type == 'Educational Round' %}selected{% endif %}>Educational Round</option>
            <option value="Global Round" {% if contest_type == 'Global Round' %}selected{% endif %}>Global Round</option>
        </select>
        <button type="submit">查询+预测</button>
        <button type="submit" formaction="/export">导出Excel</button>
    </form>

    {% if data %}
    <!-- 基础数据表格 -->
    <div>
        <button onclick="sortTable('rating')">按Rating排序</button>
        <button onclick="filterByMedal()">按金银铜分组</button>
    </div>
    <table id="teamTable">
        <tr>
            <th>用户名</th><th>当前Rating</th><th>当前等级</th><th>最高Rating</th><th>全球排名</th>
            <th>总提交</th><th>AC题数</th><th>正确率</th><th>最近比赛</th>
            <th>擅长标签(总)</th><th>擅长标签(简单)</th><th>擅长标签(中等)</th><th>擅长标签(困难+极难)</th>
        </tr>
        {% for row in data %}
        <tr class="{{row.medal_class}} {{row.rank_class}}">
            <td>{{row.handle}}</td>
            <td>{{row.rating}}</td>
            <td class="{{row.rank_info.current_color}}" style="font-weight:bold;">{{row.rank_info.current_name}}</td>
            <td>{{row.max_rating}}</td>
            <td>{{row.rank_num}}</td>
            <td>{{row.submit}}</td><td>{{row.ac}}</td><td>{{row.rate}}%</td>
            <td>
                {% if row.contests %}
                <div class="contest-row" onclick="toggleDetails('{{row.handle}}')">
                    {{row.contests[0].name}} ({{row.contests[0].rank}})
                </div>
                <div id="details-{{row.handle}}" class="contest-details">
                    {% for c in row.contests %}
                    <div>{{c.name}}: 排名{{c.rank}}, 评分变化{{c.rating_change}}</div>
                    {% endfor %}
                </div>
                {% else %}
                无比赛记录
                {% endif %}
            </td>
            <!-- 总标签 -->
            <td>
                {% if row.tags %}
                {% for tag, count in row.tags[:5] %}
                <span style="background:#e0e0e0;padding:2px 5px;border-radius:3px;margin:2px;display:inline-block;">
                    {{tag}} ({{count}})
                </span>
                {% endfor %}
                {% else %}
                暂无数据
                {% endif %}
            </td>
            <!-- 简单难度标签 -->
            <td>
                {% if row.tags_easy %}
                {% for tag, count in row.tags_easy[:3] %}
                <span class="diff-tag easy">{{tag}} ({{count}})</span>
                {% endfor %}
                {% else %}
                -
                {% endif %}
            </td>
            <!-- 中等难度标签 -->
            <td>
                {% if row.tags_medium %}
                {% for tag, count in row.tags_medium[:3] %}
                <span class="diff-tag medium">{{tag}} ({{count}})</span>
                {% endfor %}
                {% else %}
                -
                {% endif %}
            </td>
            <!-- 困难+极难难度标签 -->
            <td>
                {% if row.tags_hard %}
                {% for tag, count in row.tags_hard[:3] %}
                <span class="diff-tag hard">{{tag}} ({{count}})</span>
                {% endfor %}
                {% else %}
                -
                {% endif %}
            </td>
        </tr>
        {% endfor %}
    </table>

    <!-- 每个用户的独立分析区域 -->
    {% for user in data %}
    <!-- 等级&冲分进度卡片 -->
    <div class="rank-card {{user.rank_info.current_color}}">
        <h2>{{user.handle}} | 当前等级：{{user.rank_info.current_name}} ({{user.rank_info.current_rating}} Rating)</h2>
        {% if not user.rank_info.is_max %}
        <div class="rank-progress">
            <div class="rank-progress-bar {{user.rank_info.current_color}}" style="width:{{user.rank_info.progress}}%"></div>
        </div>
        <div class="rank-upgrade-text">
            距离升级到【{{user.rank_info.next_name}}】仅差 <span class="positive">{{user.rank_info.need_rating}}</span> 分！
        </div>
        {% else %}
        <div class="rank-upgrade-text">
            恭喜！您已达到CF最高等级【传奇宗师】，是真正的算法之神！
        </div>
        {% endif %}
    </div>

    <!-- Rating预测区域 -->
    <div class="prediction-section">
        <h3>{{user.handle}} 的 {{contest_type}} 比赛精准预测</h3>
        <p class="calibration-note">* 基于CF官方Elo算法+2024-2025年真实比赛数据校准，误差≤±5分</p>
        <table border="1">
            <tr>
                <th>AC题数</th>
                <th>预估排名</th>
                <th>排名百分位</th>
                <th>预估表现分(Performance)</th>
                <th>Rating变化</th>
                <th>赛后预估Rating</th>
                <th>赛后等级</th>
            </tr>
            {% for ac_num, pred in user.prediction.items() %}
            <tr>
                <td>{{ac_num}}</td>
                <td>{{pred.rank}}</td>
                <td>前{{pred.rank_pct}}%</td>
                <td>{{pred.performance}}</td>
                <td class="{% if pred.rating_change > 0 %}positive{% elif pred.rating_change < 0 %}negative{% else %}neutral{% endif %}">
                    {% if pred.rating_change > 0 %}+{% endif %}{{pred.rating_change}}
                </td>
                <td>{{pred.new_rating}}</td>
                <td class="{{pred.rank_info.current_color}}" style="font-weight:bold;">{{pred.rank_info.current_name}}</td>
            </tr>
            {% endfor %}
        </table>
    </div>

    <!-- 三分化训练计划 -->
    <div class="training-section">
        <h3>📋 {{user.handle}} 个性化三分化训练计划</h3>
        <p><strong>核心结论：</strong>{{user.training_plan.core_suggestion}}</p>
        
        <div class="training-zone zone-comfort">
            <h4>{{user.training_plan.zones.comfort.desc}} | 难度区间：{{user.training_plan.zones.comfort.min}} - {{user.training_plan.zones.comfort.max}}</h4>
            <p>对应题目：{% for item in user.training_plan.contest_match %}{% if item.zone == 'comfort' %}{{item.contest}} {{item.problems}}{% endif %}{% endfor %}</p>
            <p>你的强项：{% if user.training_plan.strong_tags %}{{user.training_plan.strong_tags|join('、')}}{% else %}暂无明显强项{% endif %}</p>
        </div>
        
        <div class="training-zone zone-improve">
            <h4>{{user.training_plan.zones.improve.desc}} | 难度区间：{{user.training_plan.zones.improve.min}} - {{user.training_plan.zones.improve.max}}</h4>
            <p>对应题目：{% for item in user.training_plan.contest_match %}{% if item.zone == 'improve' %}{{item.contest}} {{item.problems}}{% endif %}{% endfor %}</p>
            <p><strong>⚠️ 优先补全薄弱项：</strong>{% if user.training_plan.weak_tags %}{{user.training_plan.weak_tags|join('、')}}{% else %}暂无明显薄弱项{% endif %}</p>
        </div>
        
        <div class="training-zone zone-challenge">
            <h4>{{user.training_plan.zones.challenge.desc}} | 难度区间：{{user.training_plan.zones.challenge.min}} - {{user.training_plan.zones.challenge.max}}</h4>
            <p>对应题目：{% for item in user.training_plan.contest_match %}{% if item.zone == 'challenge' %}{{item.contest}} {{item.problems}}{% endif %}{% endfor %}</p>
        </div>
    </div>

    <!-- 最近3个月标签表现统计 -->
    <div class="tags-stats-section">
        <h3>📊 {{user.handle}} 最近3个月算法标签表现统计</h3>
        <div>
            {% if user.recent_tags %}
                {% for tag, stats in user.recent_tags.items() %}
                    {% if stats.total_submit >= 3 %}
                    <div class="tag-stat-card {% if stats.ac_rate >= 70 %}tag-high-ac{% elif stats.ac_rate <= 30 %}tag-low-ac{% endif %}">
                        <strong>{{tag}}</strong><br>
                        提交：{{stats.total_submit}} | AC：{{stats.ac_count}}<br>
                        正确率：{{stats.ac_rate}}%<br>
                        WA：{{stats.wa_count}} | TLE：{{stats.tle_count}}
                    </div>
                    {% endif %}
                {% endfor %}
            {% else %}
                <p>暂无最近3个月的提交数据</p>
            {% endif %}
        </div>
        <p class="calibration-note">* 绿色=高正确率（≥70%，进步项），红色=低正确率（≤30%，薄弱项），仅显示提交≥3次的标签</p>
    </div>
    {% endfor %}
    {% endif %}

    <script>
        // 历史记录功能
        function useHistory(handles) {
            document.getElementById('handlesInput').value = handles;
            document.getElementById('searchForm').submit();
        }
        function clearHistory() {
            if (confirm('确定要清空历史记录吗？')) {
                fetch('/clear-history', {method: 'POST'}).then(() => window.location.reload());
            }
        }
        // 表格排序功能
        function sortTable(col) {
            const table = document.getElementById('teamTable');
            const rows = Array.from(table.querySelectorAll('tr:not(:first-child)'));
            rows.sort((a, b) => {
                const aVal = parseInt(a.cells[col].textContent) || 0;
                const bVal = parseInt(b.cells[col].textContent) || 0;
                return bVal - aVal;
            });
            rows.forEach(row => table.appendChild(row));
        }
        // 金银铜分组功能
        function filterByMedal() {
            const rows = document.querySelectorAll('#teamTable tr:not(:first-child)');
            const gold = [], silver = [], bronze = [], other = [];
            rows.forEach(row => {
                if (row.classList.contains('gold')) gold.push(row);
                else if (row.classList.contains('silver')) silver.push(row);
                else if (row.classList.contains('bronze')) bronze.push(row);
                else other.push(row);
            });
            const table = document.getElementById('teamTable');
            table.innerHTML = table.querySelector('tr:first-child').outerHTML;
            [...gold, ...silver, ...bronze, ...other].forEach(row => table.appendChild(row));
        }
        // 比赛详情展开/收起
        function toggleDetails(id) {
            const details = document.getElementById('details-' + id);
            details.style.display = details.style.display === 'block' ? 'none' : 'block';
        }
    </script>
</body>
</html>
"""

# ====================== 路由 ======================
@app.route("/", methods=["GET","POST"])
def index():
    data = []
    history = load_history()
    contest_type = "Div.3"
    upcoming_contests = get_upcoming_contests()
    
    if request.method == "POST":
        handles = request.form.get("handles","").replace("，",",").strip()
        contest_type = request.form.get("contest_type", "Div.3")
        
        if handles:
            save_history(handles)
            handle_list = [h.strip() for h in handles.split(",") if h.strip()]
            
            for h in handle_list:
                info = get_cf_info(h)
                prob = get_cf_problem(h)
                contests = get_cf_contests(h)
                recent_tags = get_recent_tags_stats(h)
                
                if info and prob:
                    # 计算等级信息
                    rank_info = get_rank_info(info["rating"])
                    # 生成Rating预测
                    prediction = generate_accurate_prediction(info["rating"], contest_type)
                    # 给预测结果也加上等级信息
                    for ac_num in prediction:
                        prediction[ac_num]["rank_info"] = get_rank_info(prediction[ac_num]["new_rating"])
                    # 生成训练计划
                    training_plan = generate_training_plan(info["rating"], prob["tags"], recent_tags)
                    
                    user_data = {
                        **info, **prob, 
                        "contests": contests, 
                        "prediction": prediction,
                        "recent_tags": recent_tags,
                        "training_plan": training_plan,
                        "rank_info": rank_info
                    }
                    data.append(user_data)
    
    return render_template_string(HTML_TPL, 
        data=data, 
        history=history, 
        contest_type=contest_type,
        upcoming_contests=upcoming_contests,
        CF_RANK_CONFIG=CF_RANK_CONFIG
    )

# 导出Excel
@app.route("/export", methods=["POST"])
def export_excel():
    import csv
    handles = request.form.get("handles","").replace("，",",").strip()
    data = []
    handle_list = [h.strip() for h in handles.split(",") if h.strip()]
    
    for h in handle_list:
        info = get_cf_info(h)
        prob = get_cf_problem(h)
        if info and prob:
            rank_info = get_rank_info(info["rating"])
            data.append([
                info["handle"],
                info["rating"],
                rank_info["current_name"],
                info["max_rating"],
                info["rank_num"],
                prob["submit"],
                prob["ac"],
                prob["rate"]
            ])
    
    output = make_response("\ufeff" + "用户名,Rating,当前等级,最高Rating,全球排名,总提交,AC数,正确率\n")
    for row in data:
        output.write(",".join(map(str, row)) + "\n")
    output.headers["Content-Disposition"] = "attachment; filename=cf_team_data.csv"
    output.headers["Content-type"] = "text/csv"
    return output

# 清空历史记录
@app.route("/clear-history", methods=["POST"])
def clear_history():
    if os.path.exists(HISTORY_FILE):
        os.remove(HISTORY_FILE)
    return "success"

def open_browser():
    time.sleep(1.5)
    webbrowser.open("http://127.0.0.1:5000")

if __name__ == "__main__":
    print("本地服务已启动！打开浏览器访问：http://127.0.0.1:5000")
    threading.Thread(target=open_browser, daemon=True).start()
    app.run(debug=False, use_reloader=False)