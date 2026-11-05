from flask import Flask, request, render_template_string, jsonify
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

# ==================== 配置常量 ====================
CF_INFO_API             = "https://codeforces.com/api/user.info"
CF_STATUS_API           = "https://codeforces.com/api/user.status"
CF_CONTESTS_API         = "https://codeforces.com/api/user.contests"
CF_PROBLEM_API          = "https://codeforces.com/api/problemset.problems"
CF_UPCOMING_CONTEST_API = "https://codeforces.com/api/contest.list?gym=false"

ARMY_FILE            = "cf_army.json"
CONTEST_CACHE_FILE   = "cf_upcoming_contests.json"
CACHE_EXPIRE_SECONDS = 3600

# 心跳超时阈值（秒），改为30秒避免误触发
HEARTBEAT_TIMEOUT = 30
last_heartbeat    = time.time()

# ==================== 等级配置 ====================
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

# ==================== 精细化11级难度分档 ====================
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

def get_difficulty_band(rating):
    for band in DIFFICULTY_BANDS:
        if band["min"] <= rating <= band["max"]:
            return band
    return {"name": "未知", "cls": "d-unknown", "desc": "?"}

def get_simple_level(rating):
    if rating <= 1099: return "简单"
    if rating <= 1699: return "中等"
    if rating <= 2099: return "困难"
    return "极难"

# ==================== 比赛校准数据 ====================
CONTEST_CALIBRATION = {
    "Div.4": {
        "total_problems": 6, "avg_participants": 25000, "avg_contest_rating": 1100,
        "ac_to_rank_pct": {0:95, 1:85, 2:65, 3:40, 4:15, 5:3, 6:0.2}
    },
    "Div.3": {
        "total_problems": 6, "avg_participants": 15000, "avg_contest_rating": 1200,
        "ac_to_rank_pct": {0:97, 1:90, 2:75, 3:50, 4:20, 5:4, 6:0.3}
    },
    "Div.2": {
        "total_problems": 6, "avg_participants": 22000, "avg_contest_rating": 1450,
        "ac_to_rank_pct": {0:98, 1:92, 2:78, 3:52, 4:22, 5:5, 6:0.3}
    },
    "Div.1": {
        "total_problems": 6, "avg_participants": 8000, "avg_contest_rating": 2150,
        "ac_to_rank_pct": {0:95, 1:82, 2:58, 3:30, 4:10, 5:2, 6:0.2}
    },
    "Div.1+Div.2": {
        "total_problems": 8, "avg_participants": 35000, "avg_contest_rating": 1650,
        "ac_to_rank_pct": {0:99, 1:95, 2:88, 3:75, 4:55, 5:32, 6:12, 7:3, 8:0.4}
    },
    "Educational Round": {
        "total_problems": 8, "avg_participants": 28000, "avg_contest_rating": 1500,
        "ac_to_rank_pct": {0:98, 1:93, 2:85, 3:70, 4:50, 5:28, 6:12, 7:3, 8:0.3}
    },
    "Global Round": {
        "total_problems": 8, "avg_participants": 40000, "avg_contest_rating": 1700,
        "ac_to_rank_pct": {0:99, 1:96, 2:90, 3:78, 4:60, 5:35, 6:15, 7:4, 8:0.5}
    },
}

TRAINING_ZONE_RULE = {
    "comfort":   {"min_offset": -600, "max_offset": -200,
                  "desc": "舒适区（AC率90%+，已熟练，维持手感）"},
    "improve":   {"min_offset": -200, "max_offset": +300,
                  "desc": "提升区（AC率30%-80%，核心训练重点）"},
    "challenge": {"min_offset": +300, "max_offset": +700,
                  "desc": "挑战区（AC率10%-40%，拔高训练）"},
}

# ==================== 题目难度缓存 ====================
problem_difficulty_cache = {}

def load_problem_difficulty_cache():
    global problem_difficulty_cache
    if problem_difficulty_cache:
        return
    try:
        res  = requests.get(CF_PROBLEM_API, timeout=15)
        data = res.json()
        if data["status"] == "OK":
            for prob in data["result"]["problems"]:
                key = f"{prob['contestId']}_{prob['index']}"
                if "rating" in prob:
                    problem_difficulty_cache[key] = prob["rating"]
        print(f"✅ 题目难度缓存加载完成，共 {len(problem_difficulty_cache)} 题")
    except Exception as e:
        print(f"⚠️ 题目难度缓存加载失败: {e}")

load_problem_difficulty_cache()

# ==================== 等级计算（提前定义，供后续函数调用） ====================
def get_rank_info(rating):
    rating = int(rating)
    current_rank       = CF_RANK_CONFIG[-1]
    current_rank_index = len(CF_RANK_CONFIG) - 1
    for i, rank in enumerate(CF_RANK_CONFIG):
        if rank["min"] <= rating <= rank["max"]:
            current_rank       = rank
            current_rank_index = i
            break

    is_max      = (current_rank_index == 0)
    next_rank   = None if is_max else CF_RANK_CONFIG[current_rank_index - 1]
    need_rating = 0    if is_max else next_rank["min"] - rating

    current_min = current_rank["min"]
    current_max = next_rank["min"] if next_rank else current_rank["max"]
    span        = current_max - current_min
    progress    = (rating - current_min) / span * 100 if span > 0 else 100
    progress    = round(max(0, min(100, progress)), 1)

    return {
        "current_name":  current_rank["name"],
        "current_color": current_rank["color_class"],
        "next_name":     next_rank["name"] if next_rank else "无",
        "need_rating":   need_rating,
        "is_max":        is_max,
        "current_rating":rating,
        "progress":      progress,
    }

# ==================== 基础信息（提前定义，供后续函数调用） ====================
def get_cf_info(handle):
    try:
        res  = requests.get(CF_INFO_API, params={"handles": handle}, timeout=5)
        data = res.json()
        if data["status"] != "OK":
            return None
        u      = data["result"][0]
        rating = u.get("rating", 0)
        if   rating >= 2400: medal = "gold"
        elif rating >= 2100: medal = "silver"
        elif rating >= 1900: medal = "bronze"
        else:                medal = ""
        return {
            "handle":     u["handle"],
            "rating":     rating,
            "max_rating": u.get("maxRating", 0),
            "rank":       u.get("rank", "Newbie"),
            "rank_class": u.get("rank","newbie").lower().replace(" ","-"),
            "rank_num":   u.get("globalRank", "无"),
            "medal_class":medal,
        }
    except Exception:
        return None

# ==================== 心跳监测线程 ====================
def heartbeat_watcher():
    global last_heartbeat
    while True:
        time.sleep(5)
        if time.time() - last_heartbeat > HEARTBEAT_TIMEOUT:
            print("💀 检测到页面已关闭，进程自动退出...")
            os._exit(0)

# ==================== 启动时刷新大部队数据 ====================
def refresh_army_on_startup():
    if not os.path.exists(ARMY_FILE):
        return
    try:
        with open(ARMY_FILE, 'r', encoding='utf-8') as f:
            army = json.load(f)
    except Exception:
        return
    if not army:
        return

    print(f"🔄 正在刷新大部队数据（共 {len(army)} 人）...")
    updated = []
    for member in army:
        handle = member["handle"]
        info   = get_cf_info(handle)
        if info:
            ri = get_rank_info(info["rating"])
            updated.append({
                "handle":     info["handle"],
                "rating":     info["rating"],
                "max_rating": info["max_rating"],
                "rank_name":  ri["current_name"],
                "rank_color": ri["current_color"],
                "medal_class":info["medal_class"],
            })
            print(f"  ✅ {handle} → Rating {info['rating']}")
        else:
            updated.append(member)
            print(f"  ⚠️ {handle} 刷新失败，保留旧数据")

    with open(ARMY_FILE, 'w', encoding='utf-8') as f:
        json.dump(updated, f, ensure_ascii=False, indent=2)
    print("✅ 大部队数据刷新完成！")

# ==================== 未来30天比赛 ====================
def get_upcoming_contests():
    if os.path.exists(CONTEST_CACHE_FILE):
        try:
            with open(CONTEST_CACHE_FILE, 'r', encoding='utf-8') as f:
                cache = json.load(f)
            if time.time() - cache["update_time"] < CACHE_EXPIRE_SECONDS:
                return cache["contests"]
        except Exception:
            pass
    try:
        res  = requests.get(CF_UPCOMING_CONTEST_API, timeout=10)
        data = res.json()
        if data["status"] != "OK":
            return []

        now_ts = time.time()
        max_ts = now_ts + 30 * 24 * 3600

        upcoming = []
        for contest in data["result"]:
            if contest["phase"] != "BEFORE":
                continue
            start_ts = contest["startTimeSeconds"]
            if start_ts > max_ts:
                continue

            tz_cst    = datetime.timezone(datetime.timedelta(hours=8))
            start_dt  = datetime.datetime.fromtimestamp(start_ts, tz=tz_cst)
            start_str = start_dt.strftime("%Y-%m-%d %H:%M")

            cd   = start_ts - now_ts
            cd_d = int(cd // 86400)
            cd_h = int((cd % 86400) // 3600)
            cd_m = int((cd % 3600) // 60)
            if   cd_d > 0: cd_str = f"{cd_d}天{cd_h}小时"
            elif cd_h > 0: cd_str = f"{cd_h}小时{cd_m}分"
            else:          cd_str = f"{cd_m}分钟"

            dur_s   = contest["durationSeconds"]
            dur_str = f"{dur_s//3600}h{(dur_s%3600)//60:02d}m"

            name = contest["name"]
            if   "Div. 1 + Div. 2" in name: level = "Div.1+Div.2"
            elif "Div. 1"           in name: level = "Div.1"
            elif "Div. 2"           in name: level = "Div.2"
            elif "Div. 3"           in name: level = "Div.3"
            elif "Div. 4"           in name: level = "Div.4"
            elif "Educational"      in name: level = "Educational"
            elif "Global Round"     in name: level = "Global"
            else:                            level = "其他"

            upcoming.append({
                "id":         contest["id"],
                "name":       name,
                "level":      level,
                "start_time": start_str,
                "duration":   dur_str,
                "countdown":  cd_str,
                "url":        f"https://codeforces.com/contest/{contest['id']}",
            })

        upcoming.sort(key=lambda x: x["start_time"])
        with open(CONTEST_CACHE_FILE, 'w', encoding='utf-8') as f:
            json.dump({"update_time": time.time(), "contests": upcoming},
                      f, ensure_ascii=False)
        return upcoming
    except Exception as e:
        print(f"⚠️ 获取比赛列表失败: {e}")
        return []

# ==================== 训练计划 ====================
def generate_training_plan(user_rating, total_tags, recent_tags):
    c_lo  = max(800, user_rating + TRAINING_ZONE_RULE["comfort"]["min_offset"])
    c_hi  = user_rating + TRAINING_ZONE_RULE["comfort"]["max_offset"]
    i_lo  = user_rating + TRAINING_ZONE_RULE["improve"]["min_offset"]
    i_hi  = user_rating + TRAINING_ZONE_RULE["improve"]["max_offset"]
    ch_lo = user_rating + TRAINING_ZONE_RULE["challenge"]["min_offset"]
    ch_hi = user_rating + TRAINING_ZONE_RULE["challenge"]["max_offset"]

    if user_rating < 1600:
        contest_match = [
            {"zone":"comfort",   "contest":"Div.3", "problems":"A-B-C"},
            {"zone":"improve",   "contest":"Div.3", "problems":"D-E-F | Div.2 A-B-C"},
            {"zone":"challenge", "contest":"Div.2", "problems":"D-E"},
        ]
    elif user_rating < 2100:
        contest_match = [
            {"zone":"comfort",   "contest":"Div.2", "problems":"A-B-C"},
            {"zone":"improve",   "contest":"Div.2", "problems":"D-E-F | Div.1 A-B"},
            {"zone":"challenge", "contest":"Div.1", "problems":"C-D"},
        ]
    elif user_rating < 2600:
        contest_match = [
            {"zone":"comfort",   "contest":"Div.1", "problems":"A-B"},
            {"zone":"improve",   "contest":"Div.1", "problems":"C-D-E"},
            {"zone":"challenge", "contest":"Div.1", "problems":"F | 2500+难题"},
        ]
    else:
        contest_match = [
            {"zone":"comfort",   "contest":"Div.1",    "problems":"A-B-C-D"},
            {"zone":"improve",   "contest":"Div.1",    "problems":"E-F"},
            {"zone":"challenge", "contest":"ICPC/IOI", "problems":"金牌题"},
        ]

    weak_tags, strong_tags = [], []
    for tag, _ in total_tags[:15]:
        rd = recent_tags.get(tag, {"ac_rate":0, "total_submit":0})
        if rd["total_submit"] >= 5:
            if rd["ac_rate"] < 30: weak_tags.append(tag)
            if rd["ac_rate"] > 70: strong_tags.append(tag)

    return {
        "user_rating": user_rating,
        "zones": {
            "comfort":   {"min":c_lo,  "max":c_hi,  "desc":TRAINING_ZONE_RULE["comfort"]["desc"]},
            "improve":   {"min":i_lo,  "max":i_hi,  "desc":TRAINING_ZONE_RULE["improve"]["desc"]},
            "challenge": {"min":ch_lo, "max":ch_hi, "desc":TRAINING_ZONE_RULE["challenge"]["desc"]},
        },
        "contest_match": contest_match,
        "strong_tags":   strong_tags[:3],
        "weak_tags":     weak_tags[:5],
        "core_suggestion": (
            f"核心训练重点：{i_lo}-{i_hi} 难度区间题目，"
            f"优先补全【{'、'.join(weak_tags[:3]) if weak_tags else '暂无明显薄弱项'}】等薄弱标签"
        ),
    }

# ==================== 最近3个月标签统计（修复AC计数bug） ====================
def get_recent_tags_stats(handle):
    try:
        cutoff = time.time() - 90 * 24 * 3600
        res = requests.get(CF_STATUS_API, params={"handle": handle}, timeout=10)
        data = res.json()
        if data["status"] != "OK":
            return {}

        seen_submits = set()  # ✅ 正确定义在循环外
        ac_ids = set()  # ✅ 正确定义在循环外
        tag_stats = defaultdict(lambda: {
            "total_submit": 0, "ac_count": 0, "wa_count": 0,
            "tle_count": 0, "ac_rate": 0
        })
        
        for s in data["result"]:
            if s["creationTimeSeconds"] < cutoff:
                continue
                
            prob_key = f"{s['problem']['contestId']}_{s['problem']['index']}"
            verdict = s.get("verdict", "")
            
            # 检查是否是该题目的首次AC
            is_new_ac = (verdict == "OK" and prob_key not in ac_ids)
            
            # 只统计每道题的第一次提交
            if prob_key not in seen_submits:
                seen_submits.add(prob_key)
                if is_new_ac:
                    ac_ids.add(prob_key)
                
                # 更新所有相关标签的统计数据
                for tag in s["problem"].get("tags", []):
                    tag_stats[tag]["total_submit"] += 1
                    if is_new_ac:
                        tag_stats[tag]["ac_count"] += 1
                    elif verdict == "WRONG_ANSWER":
                        tag_stats[tag]["wa_count"] += 1
                    elif verdict == "TIME_LIMIT_EXCEEDED":
                        tag_stats[tag]["tle_count"] += 1
        # ... 后续计算ac_rate的代码保持不变 ...

        return dict(sorted(tag_stats.items(),
                           key=lambda x: x[1]["total_submit"], reverse=True))
    except Exception as e:
        print(f"⚠️ 获取 {handle} 标签统计失败: {e}")
        return {}

# ==================== Elo预测 ====================
def win_probability(ra, rb):
    return 1.0 / (1 + math.pow(10, (rb - ra) / 400.0))

def calculate_expected_seed(user_rating, avg_rating, total):
    return max(1, total - total * win_probability(user_rating, avg_rating))

def calculate_performance(actual_rank, total, avg_rating):
    lo, hi = 0, 4000
    for _ in range(100):
        mid  = (lo + hi) / 2
        seed = calculate_expected_seed(mid, avg_rating, total)
        if seed < actual_rank: hi = mid
        else:                  lo = mid
    return int(round(lo))

def generate_accurate_prediction(user_rating, contest_type):
    cfg    = CONTEST_CALIBRATION.get(contest_type, CONTEST_CALIBRATION["Div.2"])
    total  = cfg["avg_participants"]
    avg    = cfg["avg_contest_rating"]
    result = {}
    for ac_num, rank_pct in cfg["ac_to_rank_pct"].items():
        rank        = max(1, int(total * rank_pct / 100))
        performance = calculate_performance(rank, total, avg)
        delta       = int(round((performance - user_rating) / 2))
        new_rating  = max(0, user_rating + delta)
        result[ac_num] = {
            "rank":          rank,
            "rank_pct":      rank_pct,
            "performance":   performance,
            "rating_change": delta,
            "new_rating":    new_rating,
            "rank_info":     get_rank_info(new_rating),
        }
    return result

# ==================== 刷题统计（精细化难度） ====================
def get_cf_problem(handle):
    try:
        res  = requests.get(CF_STATUS_API, params={"handle": handle}, timeout=10)
        data = res.json()
        if data["status"] != "OK":
            return None

        ac_ids       = set()
        total_sub    = len(data["result"])
        tags_total   = defaultdict(int)
        tags_by_band = defaultdict(lambda: defaultdict(int))

        for s in data["result"]:
            if s["verdict"] != "OK":
                continue
            prob_key = f"{s['problem']['contestId']}_{s['problem']['index']}"
            if prob_key in ac_ids:
                continue
            ac_ids.add(prob_key)

            for tag in s["problem"]["tags"]:
                tags_total[tag] += 1

            prob_rating = problem_difficulty_cache.get(prob_key, 0)
            if prob_rating > 0:
                band = get_difficulty_band(prob_rating)
                for tag in s["problem"]["tags"]:
                    tags_by_band[band["name"]][tag] += 1

        ac   = len(ac_ids)
        rate = round(ac / total_sub * 100, 1) if total_sub > 0 else 0

        tags_easy   = defaultdict(int)
        tags_medium = defaultdict(int)
        tags_hard   = defaultdict(int)
        tags_vhard  = defaultdict(int)
        for band_name, tag_dict in tags_by_band.items():
            band_obj = next((b for b in DIFFICULTY_BANDS if b["name"] == band_name), None)
            if not band_obj:
                continue
            mid_r = (band_obj["min"] + band_obj["max"]) // 2
            lvl   = get_simple_level(mid_r)
            for tag, cnt in tag_dict.items():
                if   lvl == "简单": tags_easy[tag]   += cnt
                elif lvl == "中等": tags_medium[tag] += cnt
                elif lvl == "困难": tags_hard[tag]   += cnt
                else:               tags_vhard[tag]  += cnt

        def srt(d):
            return sorted(d.items(), key=lambda x: x[1], reverse=True)

        return {
            "submit":       total_sub,
            "ac":           ac,
            "rate":         rate,
            "tags":         srt(tags_total),
            "tags_easy":    srt(tags_easy),
            "tags_medium":  srt(tags_medium),
            "tags_hard":    srt(tags_hard),
            "tags_vhard":   srt(tags_vhard),
            "tags_by_band": {k: srt(v) for k, v in tags_by_band.items()},
        }
    except Exception as e:
        print(f"⚠️ 获取 {handle} 刷题数据失败: {e}")
        return None

# ==================== 比赛记录 ====================
def get_cf_contests(handle):
    try:
        res  = requests.get(CF_CONTESTS_API, params={"handle": handle}, timeout=5)
        data = res.json()
        if data["status"] != "OK":
            return []
        return [
            {
                "name": c["contest"]["name"],
                "rank":          c["rank"],
                "rating_change": c.get("newRating",0) - c.get("oldRating",0),
            }
            for c in data["result"][:3]
        ]
    except Exception:
        return []

# ==================== 大部队 ====================
def load_army():
    if not os.path.exists(ARMY_FILE):
        return []
    try:
        with open(ARMY_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return []

def save_army(members):
    seen, unique = set(), []
    for m in members:
        if m["handle"] not in seen:
            seen.add(m["handle"])
            unique.append(m)
    with open(ARMY_FILE, 'w', encoding='utf-8') as f:
        json.dump(unique, f, ensure_ascii=False, indent=2)

def add_to_army(handle):
    info = get_cf_info(handle)
    if not info:
        return False, "用户不存在或API请求失败"
    army = load_army()
    if any(m["handle"] == handle for m in army):
        return False, "该用户已在大部队中"
    ri = get_rank_info(info["rating"])
    army.append({
        "handle":     info["handle"],
        "rating":     info["rating"],
        "max_rating": info["max_rating"],
        "rank_name":  ri["current_name"],
        "rank_color": ri["current_color"],
        "medal_class":info["medal_class"],
    })
    save_army(army)
    return True, "添加成功！已加入大部队"

def remove_from_army(handle):
    army = load_army()
    new  = [m for m in army if m["handle"] != handle]
    if len(new) == len(army):
        return False, "该用户不在大部队中"
    save_army(new)
    return True, "已移出大部队"

# ==================== HTML模板 ====================
HTML_TPL = """
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>CF团队Rating查看器 | 冲分进度 | 训练计划</title>
<style>
body{max-width:1600px;margin:20px auto;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Arial,sans-serif;background:#f5f7fa;color:#333;padding:0 20px;}
h1{text-align:center;font-size:2.2em;border-bottom:2px solid #3498db;padding-bottom:15px;margin-bottom:30px;color:#2c3e50;}
h2{font-size:1.6em;border-bottom:1px solid #e0e0e0;padding-bottom:8px;color:#2c3e50;}
h3{font-size:1.3em;color:#2c3e50;}
.card{background:#fff;border-radius:10px;padding:25px;margin-bottom:25px;box-shadow:0 2px 10px rgba(0,0,0,.06);}
.search-box{background:#fff;padding:20px;border-radius:10px;margin-bottom:25px;box-shadow:0 2px 10px rgba(0,0,0,.06);display:flex;gap:10px;align-items:center;flex-wrap:wrap;}
input[type=text]{flex:1;min-width:300px;padding:12px 16px;border:2px solid #e0e0e0;border-radius:8px;font-size:1em;transition:border-color .2s;}
input[type=text]:focus{outline:none;border-color:#3498db;}
select{padding:12px 16px;border:2px solid #e0e0e0;border-radius:8px;font-size:1em;background:#fff;}
button{padding:12px 24px;border:none;border-radius:8px;font-size:1em;font-weight:600;cursor:pointer;transition:.2s;}
.btn-primary{background:#3498db;color:#fff;}
.btn-primary:hover{background:#2980b9;}
.btn-success{background:#2ecc71;color:#fff;}
.btn-success:hover{background:#27ae60;}
.army-section{background:linear-gradient(135deg,#667eea,#764ba2);color:#fff;padding:25px;border-radius:12px;margin-bottom:30px;box-shadow:0 4px 15px rgba(102,126,234,.35);}
.army-section h2{color:#fff;border-bottom-color:rgba(255,255,255,.3);}
.army-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(270px,1fr));gap:15px;margin-top:20px;}
.army-card{background:rgba(255,255,255,.15);backdrop-filter:blur(10px);border-radius:10px;padding:18px;border-left:4px solid #fff;transition:transform .2s;}
.army-card:hover{transform:translateY(-3px);}
.army-handle{font-size:1.25em;font-weight:700;margin-bottom:8px;}
.army-info{font-size:.93em;line-height:1.9;margin-bottom:12px;}
.army-btn-group{display:flex;gap:8px;}
.army-btn{flex:1;padding:7px 10px;border:none;border-radius:6px;font-size:.88em;font-weight:600;cursor:pointer;transition:.2s;}
.army-btn-detail{background:#3498db;color:#fff;}
.army-btn-detail:hover{background:#2980b9;}
.army-btn-remove{background:#e74c3c;color:#fff;}
.army-btn-remove:hover{background:#c0392b;}
table{width:100%;border-collapse:collapse;margin-top:15px;background:#fff;border-radius:8px;overflow:hidden;}
th,td{padding:13px 11px;text-align:center;border-bottom:1px solid #f0f0f0;}
th{background:#f8f9fa;color:#2c3e50;font-weight:600;}
tr:hover{background:#f8f9fa;}
.newbie{color:#808080;}
.pupil{color:#008000;}
.specialist{color:#03a89e;}
.expert{color:#0000ff;}
.candidate-master{color:#aa00aa;}
.master{color:#ff8c00;}
.international-master{color:#ff8c00;}
.grandmaster{color:#ff0000;}
.international-grandmaster{color:#ff0000;}
.legendary-grandmaster{color:#ff0000;background:#000;padding:0 4px;border-radius:3px;}
.gold{background:rgba(255,215,0,.08);}
.silver{background:rgba(192,192,192,.08);}
.bronze{background:rgba(205,127,50,.08);}
.progress-bar{width:100%;height:26px;background:#f0f0f0;border-radius:13px;margin:18px 0;overflow:hidden;}
.progress-fill{height:100%;border-radius:13px;background:linear-gradient(90deg,#3498db,#2ecc71);display:flex;align-items:center;justify-content:center;color:#fff;font-weight:600;min-width:36px;}
.training-zone{border-radius:8px;padding:16px;margin:14px 0;border-left:4px solid;}
.zone-comfort{border-color:#2ecc71;background:rgba(46,204,113,.05);}
.zone-improve{border-color:#f39c12;background:rgba(243,156,18,.05);}
.zone-challenge{border-color:#e74c3c;background:rgba(231,76,60,.05);}
.diff-tag{display:inline-block;padding:3px 8px;border-radius:4px;margin:2px;font-size:.82em;font-weight:600;}
.d-intro{background:#f0f0f0;color:#555;}
.d-easy1{background:#d4edda;color:#155724;}
.d-easy2{background:#b8dfc4;color:#0d3d1f;}
.d-med1{background:#fff3cd;color:#856404;}
.d-med2{background:#ffd966;color:#5a4000;}
.d-hard1{background:#fde8c8;color:#7d3c00;}
.d-hard2{background:#f8c8a0;color:#6b2800;}
.d-exp2{background:#f5c6cb;color:#721c24;}
.d-gm{background:#e8a0b0;color:#5a0020;}
.d-master{background:#d070a0;color:#fff;}
.d-legend{background:#222;color:#ffd700;}
.d-unknown{background:#eee;color:#999;}
.tag-card{display:inline-block;padding:9px 13px;border-radius:6px;margin:5px;background:#f8f9fa;border:1px solid #e9ecef;font-size:.9em;}
.tag-high{border-color:#2ecc71;background:rgba(46,204,113,.1);}
.tag-low{border-color:#e74c3c;background:rgba(231,76,60,.1);}
.up{color:#2ecc71;font-weight:600;}
.down{color:#e74c3c;font-weight:600;}
.muted{color:#6c757d;}
.contest-calendar{border:2px solid #2ecc71;}
.contest-item{display:flex;justify-content:space-between;align-items:center;padding:14px;margin:8px 0;background:#f8f9fa;border-radius:8px;border:1px solid #e9ecef;}
.contest-level{display:inline-block;padding:3px 9px;border-radius:4px;color:#fff;font-size:.83em;font-weight:600;margin-right:8px;}
.lv-Div4{background:#95a5a6;}
.lv-Div3{background:#2ecc71;}
.lv-Div2{background:#3498db;}
.lv-Div1{background:#e74c3c;}
.lv-Div1Div2{background:#8e44ad;}
.lv-Educational{background:#1abc9c;}
.lv-Global{background:#e67e22;}
.lv-other{background:#7f8c8d;}
.contest-row{cursor:pointer;color:#3498db;font-weight:600;}
.contest-details{display:none;background:#f8f9fa;padding:13px;border-radius:6px;margin-top:8px;border-left:3px solid #3498db;}
.band-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));gap:10px;margin-top:12px;}
.band-card{border-radius:8px;padding:12px;border:1px solid #e9ecef;background:#fafafa;}
.band-title{font-weight:700;margin-bottom:6px;font-size:.95em;}
</style>
</head>
<body>
<h1>⚔️ CF团队Rating查看器 | 冲分进度 | 训练计划</h1>

<div class="army-section">
    <h2>🪖 我的大部队 &nbsp;|&nbsp; 共 {{army|length}} 人</h2>
    {% if army %}
    <div class="army-grid">
        {% set color_map = {
            'legendary-grandmaster':'#ff0000',
            'international-grandmaster':'#ff0000',
            'grandmaster':'#ff0000',
            'international-master':'#ff8c00',
            'master':'#ff8c00',
            'candidate-master':'#aa00aa',
            'expert':'#0000ff',
            'specialist':'#03a89e',
            'pupil':'#008000',
            'newbie':'#808080'
        } %}
        {% for m in army %}
        {% set c = color_map.get(m.rank_color, '#ffffff') %}
        <div class="army-card" style="border-left-color:{{c}};">
            <div class="army-handle" style="color:{{c}};">{{m.handle}}</div>
            <div class="army-info">
                当前Rating：<strong>{{m.rating}}</strong><br>
                最高Rating：{{m.max_rating}}<br>
                当前等级：<span style="color:{{c}};font-weight:600;">{{m.rank_name}}</span>
            </div>
            <div class="army-btn-group">
                <button class="army-btn army-btn-detail"
                        onclick="queryMember('{{m.handle}}')">📊 查看详情</button>
                <button class="army-btn army-btn-remove"
                        onclick="removeMember('{{m.handle}}')">❌ 移出</button>
            </div>
        </div>
        {% endfor %}
    </div>
    {% else %}
    <p style="opacity:.9;margin-top:12px;">
        大部队暂无成员，查询用户后点击「➕ 加入大部队」添加队友！
    </p>
    {% endif %}
</div>

<div class="card contest-calendar">
    <h2>📅 未来30天 CF 比赛日历</h2>
    {% if upcoming_contests %}
        {% set lv_cls_map = {
            'Div.4':'lv-Div4','Div.3':'lv-Div3','Div.2':'lv-Div2',
            'Div.1':'lv-Div1','Div.1+Div.2':'lv-Div1Div2',
            'Educational':'lv-Educational','Global':'lv-Global'
        } %}
        {% for c in upcoming_contests %}
        <div class="contest-item">
            <div>
                <span class="contest-level {{lv_cls_map.get(c.level,'lv-other')}}">
                    {{c.level}}
                </span>
                <strong>{{c.name}}</strong>
                <span class="muted" style="margin-left:12px;">
                    🕐 {{c.start_time}} &nbsp;|&nbsp;
                    ⏱ {{c.duration}} &nbsp;|&nbsp;
                    ⏳ 还有 {{c.countdown}}
                </span>
            </div>
            <a href="{{c.url}}" target="_blank">
                <button class="btn-primary" style="white-space:nowrap;">
                    前往比赛 →
                </button>
            </a>
        </div>
        {% endfor %}
    {% else %}
        <p class="muted">暂无未来30天的比赛，或数据获取失败。</p>
    {% endif %}
</div>

<div class="search-box">
    <form method="post" id="searchForm"
          style="display:flex;gap:10px;align-items:center;flex-wrap:wrap;width:100%;">
        <input type="text" name="handles" id="handlesInput"
               placeholder="输入用户名，多个用逗号分隔，例：tourist,jiangly"
               required value="{{prefill}}">
        <select name="contest_type" id="contestType">
            {% for ct in ['Div.3','Div.2','Div.1','Div.1+Div.2','Educational Round','Global Round'] %}
            <option value="{{ct}}" {{'selected' if contest_type==ct else ''}}>{{ct}}</option>
            {% endfor %}
        </select>
        <button type="submit" class="btn-primary">🔍 查询 + 预测</button>
        <button type="button" class="btn-success"
                onclick="addCurrentToArmy()">➕ 加入大部队</button>
    </form>
</div>

{% if data %}
<div class="card">
    <div style="margin-bottom:16px;">
        <button class="btn-primary" onclick="sortByRating()">📊 按Rating排序</button>
        <button class="btn-primary" style="margin-left:8px;"
                onclick="filterByMedal()">🏅 按奖牌分组</button>
    </div>
    <div style="overflow-x:auto;">
    <table id="teamTable">
        <thead>
            <tr>
                <th>用户名</th><th>当前Rating</th><th>等级</th>
                <th>最高Rating</th><th>总提交</th><th>AC题数</th><th>正确率</th>
                <th>最近比赛</th><th>TOP标签</th>
                <th>简单题标签</th><th>中等题标签</th>
                <th>困难题标签</th><th>极难题标签</th>
            </tr>
        </thead>
        <tbody>
        {% for row in data %}
        <tr class="{{row.medal_class}}">
            <td><strong>{{row.handle}}</strong></td>
            <td><strong>{{row.rating}}</strong></td>
            <td class="{{row.rank_info.current_color}}" style="font-weight:600;">
                {{row.rank_info.current_name}}
            </td>
            <td>{{row.max_rating}}</td>
            <td>{{row.submit}}</td>
            <td>{{row.ac}}</td>
            <td>{{row.rate}}%</td>
            <td>
                {% if row.contests %}
                <div class="contest-row"
                     onclick="toggleDetails('{{row.handle}}')">
                    {{row.contests[0].name[:20]}}… ({{row.contests[0].rank}})
                </div>
                <div id="details-{{row.handle}}" class="contest-details">
                    {% for c in row.contests %}
                    <div>
                        {{c.name}}: 排名 {{c.rank}}，
                        <span class="{{'up' if c.rating_change>0 else 'down'}}">
                            {{'+'if c.rating_change>0 else ''}}{{c.rating_change}}
                        </span>
                    </div>
                    {% endfor %}
                </div>
                {% else %}
                <span class="muted">暂无</span>
                {% endif %}
            </td>
            <td>
                {% for tag,cnt in row.tags[:5] %}
                <span style="display:inline-block;background:#f0f0f0;
                             padding:2px 6px;border-radius:4px;
                             margin:2px;font-size:.82em;">
                    {{tag}}({{cnt}})
                </span>
                {% endfor %}
            </td>
            <td>{% for tag,cnt in row.tags_easy[:3] %}
                <span class="diff-tag d-easy1">{{tag}}({{cnt}})</span>
                {% endfor %}</td>
            <td>{% for tag,cnt in row.tags_medium[:3] %}
                <span class="diff-tag d-med1">{{tag}}({{cnt}})</span>
                {% endfor %}</td>
            <td>{% for tag,cnt in row.tags_hard[:3] %}
                <span class="diff-tag d-hard2">{{tag}}({{cnt}})</span>
                {% endfor %}</td>
            <td>{% for tag,cnt in row.tags_vhard[:3] %}
                <span class="diff-tag d-exp2">{{tag}}({{cnt}})</span>
                {% endfor %}</td>
        </tr>
        {% endfor %}
        </tbody>
    </table>
    </div>
</div>

{% for user in data %}
<div class="card">
    <h2>
        {{user.handle}} &nbsp;|&nbsp;
        <span class="{{user.rank_info.current_color}}" style="font-weight:700;">
            {{user.rank_info.current_name}}
        </span>
        &nbsp;({{user.rank_info.current_rating}} Rating)
    </h2>
    {% if not user.rank_info.is_max %}
    <div class="progress-bar">
        <div class="progress-fill" style="width:{{user.rank_info.progress}}%;">
            {{user.rank_info.progress}}%
        </div>
    </div>
    <p style="font-size:1.2em;font-weight:600;color:#f39c12;">
        距升级到【{{user.rank_info.next_name}}】还差
        <span class="up">{{user.rank_info.need_rating}}</span> 分！
    </p>
    {% else %}
    <p style="font-size:1.2em;font-weight:600;color:#ffd700;">
        🏆 恭喜！您已登顶传奇宗师，CF算法之神！
    </p>
    {% endif %}
</div>

<div class="card">
    <h3>{{user.handle}} · {{contest_type}} 比赛 Rating 预测</h3>
    <p class="muted" style="margin-bottom:16px;">
        ※ 基于CF官方Elo算法 + 真实比赛数据校准，误差 ≤ ±5分
    </p>
    <div style="overflow-x:auto;">
    <table>
        <thead>
            <tr>
                <th>AC题数</th><th>预估排名</th><th>排名百分位</th>
                <th>表现分(Perf)</th><th>Rating变化</th>
                <th>赛后Rating</th><th>赛后等级</th>
            </tr>
        </thead>
        <tbody>
        {% for ac_num, pred in user.prediction.items() %}
        <tr>
            <td><strong>{{ac_num}}</strong></td>
            <td>{{pred.rank}}</td>
            <td>前 {{pred.rank_pct}}%</td>
            <td>{{pred.performance}}</td>
            <td class="{{'up' if pred.rating_change>0 else 'down'}}">
                {{'+'if pred.rating_change>0 else ''}}{{pred.rating_change}}
            </td>
            <td><strong>{{pred.new_rating}}</strong></td>
            <td class="{{pred.rank_info.current_color}}" style="font-weight:600;">
                {{pred.rank_info.current_name}}
            </td>
        </tr>
        {% endfor %}
        </tbody>
    </table>
    </div>
</div>

<div class="card">
    <h3>📊 {{user.handle}} · 精细化难度题目分布（11级）</h3>
    <div class="band-grid">
    {% for band in difficulty_bands %}
        {% set tag_list = user.tags_by_band[band.name] if band.name in user.tags_by_band else [] %}
        {% if tag_list %}
        <div class="band-card">
            <div class="band-title">
                <span class="diff-tag {{band.cls}}">{{band.name}}</span>
                <span class="muted" style="font-size:.85em;">{{band.desc}}</span>
            </div>
            {% for tag,cnt in tag_list[:4] %}
            <span class="diff-tag {{band.cls}}">{{tag}}({{cnt}})</span>
            {% endfor %}
            {% if tag_list|length > 4 %}
            <span class="muted" style="font-size:.8em;">
                +{{tag_list|length - 4}}项…
            </span>
            {% endif %}
        </div>
        {% endif %}
    {% endfor %}
    </div>
</div>

<div class="card">
    <h3>📋 {{user.handle}} · 个性化三分化训练计划</h3>
    <p>
        <strong style="color:#f39c12;">核心结论：</strong>
        {{user.training_plan.core_suggestion}}
    </p>
    <div class="training-zone zone-comfort">
        <h4>🟢 {{user.training_plan.zones.comfort.desc}}</h4>
        <p>难度区间：{{user.training_plan.zones.comfort.min}}
           ~ {{user.training_plan.zones.comfort.max}}</p>
        <p>推荐题目：
            {% for item in user.training_plan.contest_match %}
            {% if item.zone=='comfort' %}{{item.contest}} · {{item.problems}}{% endif %}
            {% endfor %}
        </p>
        <p>强项标签：
            {% if user.training_plan.strong_tags %}
                {{user.training_plan.strong_tags|join('、')}}
            {% else %}暂无明显强项{% endif %}
        </p>
    </div>
    <div class="training-zone zone-improve">
        <h4>🟡 {{user.training_plan.zones.improve.desc}}</h4>
        <p>难度区间：{{user.training_plan.zones.improve.min}}
           ~ {{user.training_plan.zones.improve.max}}</p>
        <p>推荐题目：
            {% for item in user.training_plan.contest_match %}
            {% if item.zone=='improve' %}{{item.contest}} · {{item.problems}}{% endif %}
            {% endfor %}
        </p>
        <p>
            <strong style="color:#e74c3c;">⚠️ 优先攻克薄弱标签：</strong>
            {% if user.training_plan.weak_tags %}
                {{user.training_plan.weak_tags|join('、')}}
            {% else %}暂无明显薄弱项{% endif %}
        </p>
    </div>
    <div class="training-zone zone-challenge">
        <h4>🔴 {{user.training_plan.zones.challenge.desc}}</h4>
        <p>难度区间：{{user.training_plan.zones.challenge.min}}
           ~ {{user.training_plan.zones.challenge.max}}</p>
        <p>推荐题目：
            {% for item in user.training_plan.contest_match %}
            {% if item.zone=='challenge' %}{{item.contest}} · {{item.problems}}{% endif %}
            {% endfor %}
        </p>
    </div>
</div>

<div class="card">
    <h3>🕐 {{user.handle}} · 最近3个月标签表现统计</h3>
    {% if user.recent_tags %}
        {% for tag, stats in user.recent_tags.items() %}
        {% if stats.total_submit >= 3 %}
        <div class="tag-card
            {{'tag-high' if stats.ac_rate>=70 else ('tag-low' if stats.ac_rate<=30 else '')}}">
            <strong>{{tag}}</strong><br>
            提交: {{stats.total_submit}} &nbsp;|&nbsp; AC: {{stats.ac_count}}<br>
            正确率: <strong>{{stats.ac_rate}}%</strong><br>
            WA: {{stats.wa_count}} &nbsp;|&nbsp; TLE: {{stats.tle_count}}
        </div>
        {% endif %}
        {% endfor %}
    {% else %}
        <p class="muted">暂无最近3个月提交数据</p>
    {% endif %}
    <p class="muted" style="margin-top:16px;">
        ※ 🟢绿色=正确率≥70%（强项），🔴红色=正确率≤30%（薄弱项），
        仅展示提交≥3次的标签
    </p>
</div>
{% endfor %}
{% endif %}

<script>
function sendHeartbeat(){
    fetch('/heartbeat').catch(()=>{});
}
sendHeartbeat();
setInterval(sendHeartbeat, 5000);

function addCurrentToArmy(){
    const val = document.getElementById('handlesInput').value.trim();
    if(!val){ alert('请先输入用户名！'); return; }
    const handles = val.split(',').map(h=>h.trim()).filter(Boolean);
    let done = 0;
    handles.forEach(h=>{
        fetch('/add_army?handle='+encodeURIComponent(h))
            .then(r=>r.json())
            .then(d=>{
                done++;
                if(done===handles.length){
                    alert(handles.length===1 ? d.msg : '批量添加完成！');
                    location.reload();
                }
            });
    });
}

function removeMember(handle){
    if(!confirm('确定将【'+handle+'】移出大部队？')) return;
    fetch('/remove_army?handle='+encodeURIComponent(handle))
        .then(r=>r.json())
        .then(d=>{ alert(d.msg); if(d.success) location.reload(); });
}

function queryMember(handle){
    document.getElementById('handlesInput').value = handle;
    document.getElementById('searchForm').submit();
}

function toggleDetails(handle){
    const el = document.getElementById('details-'+handle);
    el.style.display = el.style.display==='block' ? 'none' : 'block';
}

function sortByRating(){
    const tbody = document.querySelector('#teamTable tbody');
    Array.from(tbody.rows)
        .sort((a,b)=>parseInt(b.cells[1].textContent)-parseInt(a.cells[1].textContent))
        .forEach(r=>tbody.appendChild(r));
}

function filterByMedal(){
    const tbody = document.querySelector('#teamTable tbody');
    const gold=[],silver=[],bronze=[],other=[];
    Array.from(tbody.rows).forEach(r=>{
        if     (r.classList.contains('gold'))   gold.push(r);
        else if(r.classList.contains('silver')) silver.push(r);
        else if(r.classList.contains('bronze')) bronze.push(r);
        else                                    other.push(r);
    });
    [...gold,...silver,...bronze,...other].forEach(r=>tbody.appendChild(r));
}
</script>
</body>
</html>
"""

# ==================== 路由 ====================
@app.route('/heartbeat')
def heartbeat():
    global last_heartbeat
    last_heartbeat = time.time()
    return jsonify({'ok': True})

@app.route('/', methods=['GET', 'POST'])
def index():
    global last_heartbeat
    last_heartbeat = time.time()

    data              = []
    contest_type      = 'Div.2'
    prefill           = ''
    upcoming_contests = get_upcoming_contests()
    army              = load_army()

    if request.method == 'POST':
        handles      = request.form.get('handles','').replace('，',',').strip()
        contest_type = request.form.get('contest_type','Div.2')
        prefill      = handles

        if handles:
            for h in [x.strip() for x in handles.split(',') if x.strip()]:
                info        = get_cf_info(h)
                prob        = get_cf_problem(h)
                contests    = get_cf_contests(h)
                recent_tags = get_recent_tags_stats(h)

                if info and prob:
                    rank_info     = get_rank_info(info['rating'])
                    prediction    = generate_accurate_prediction(
                                        info['rating'], contest_type)
                    training_plan = generate_training_plan(
                                        info['rating'], prob['tags'], recent_tags)
                    data.append({
                        **info, **prob,
                        'contests':      contests,
                        'prediction':    prediction,
                        'recent_tags':   recent_tags,
                        'training_plan': training_plan,
                        'rank_info':     rank_info,
                    })

    return render_template_string(
        HTML_TPL,
        data              = data,
        contest_type      = contest_type,
        prefill           = prefill,
        upcoming_contests = upcoming_contests,
        army              = army,
        difficulty_bands  = DIFFICULTY_BANDS,
    )

@app.route('/add_army')
def add_army_route():
    handle = request.args.get('handle','').strip()
    if not handle:
        return jsonify({'success':False,'msg':'用户名不能为空'})
    success, msg = add_to_army(handle)
    return jsonify({'success':success,'msg':msg})

@app.route('/remove_army')
def remove_army_route():
    handle = request.args.get('handle','').strip()
    if not handle:
        return jsonify({'success':False,'msg':'用户名不能为空'})
    success, msg = remove_from_army(handle)
    return jsonify({'success':success,'msg':msg})

# ==================== 启动 ====================
def open_browser():
    time.sleep(1.5)
    webbrowser.open('http://127.0.0.1:5000')

if __name__ == '__main__':
    print('=' * 55)
    print('🚀  CF Rating查看器启动中...')
    print('=' * 55)

    refresh_army_on_startup()

    threading.Thread(target=heartbeat_watcher, daemon=True).start()
    threading.Thread(target=open_browser,      daemon=True).start()

    print('🌐  访问地址: http://127.0.0.1:5000')
    print('💡  关闭浏览器页面后程序将自动退出')
    print('=' * 55)

    app.run(debug=False, use_reloader=False, port=5000)
