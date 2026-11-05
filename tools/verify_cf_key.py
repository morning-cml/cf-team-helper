# -*- coding: utf-8 -*-
"""验证 CF API Key 能否访问 Gym 比赛的题目列表。

这是「ICPC 比赛库」能否显示精确完成度（3/13 而非"已解出 3 题"）的前提。
匿名调用 contest.standings 取 gym 会返回 "You have to be authenticated to use this method"，
但 CF 官方没说明用 API Key 认证后是否就够 —— 所以先花两分钟实测，别为它白写一套子系统。

用法
----
1. 打开 https://codeforces.com/settings/api ，点 "Add API key"，取得 key 与 secret。
2. 在项目根目录建文件 data/cf_api.json，内容：

       {"key": "你的key", "secret": "你的secret"}

3. 运行：  python tools/verify_cf_key.py

密钥只存在你本机的 data/ 下（已被 .gitignore 排除），不会进版本库。
"""
import hashlib
import json
import os
import random
import string
import sys
import time

import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="backslashreplace")
    except Exception:
        pass

from cfhelper.paths import data_path

API = "https://codeforces.com/api"


def signed_params(method, params, key, secret):
    """按 CF 规则给请求签名。

    apiSig = <rand> + sha512( <rand>/<method>?<按字典序排好的参数>#<secret> )
    参数需按 (key, value) 字典序排序后用 & 连接。
    """
    p = dict(params)
    p["apiKey"] = key
    p["time"] = str(int(time.time()))
    rand = "".join(random.choice(string.ascii_lowercase + string.digits) for _ in range(6))
    query = "&".join(f"{k}={v}" for k, v in sorted(p.items(), key=lambda kv: (kv[0], str(kv[1]))))
    to_hash = f"{rand}/{method}?{query}#{secret}"
    p["apiSig"] = rand + hashlib.sha512(to_hash.encode()).hexdigest()
    return p


def call(method, params, key=None, secret=None):
    p = signed_params(method, params, key, secret) if key else params
    try:
        r = requests.get(f"{API}/{method}", params=p, timeout=25)
        return r.json()
    except Exception as e:
        return {"status": "EXCEPTION", "comment": str(e)}


def main():
    path = data_path("cf_api.json")
    if not os.path.exists(path):
        print(f"没找到 {path}")
        print("请先按本文件顶部的说明创建它（内容：{\"key\": \"...\", \"secret\": \"...\"}）")
        return 1
    cfg = json.load(open(path, encoding="utf-8"))
    key, secret = cfg.get("key", ""), cfg.get("secret", "")
    if not key or not secret:
        print("cf_api.json 里 key 或 secret 为空")
        return 1
    print(f"读到密钥：key={key[:6]}…（长度 {len(key)}）secret 已加载（长度 {len(secret)}）\n")

    # 1) 先用一个匿名也能调的方法，确认签名算法本身没写错
    print("[1/3] 校验签名算法（对 user.info 签名调用）")
    r = call("user.info", {"handles": "tourist"}, key, secret)
    if r.get("status") == "OK":
        print("      OK —— 签名正确，密钥有效 ✔\n")
    else:
        print(f"      FAILED: {r.get('comment')}")
        print("      => 签名或密钥有问题，后面的测试无意义\n")
        return 1

    # 2) 关键测试：带签名取 gym 比赛的题目列表
    print("[2/3] 关键测试：带签名调 contest.standings 取 gym 题目列表")
    gyms = [(105992, "2025 上海市赛（你提交过）"),
            (105255, "2023 ICPC World Finals"),
            (105578, "2024 ICPC Asia 沈阳区域赛")]
    ok_count = 0
    for cid, note in gyms:
        r = call("contest.standings", {"contestId": cid, "from": 1, "count": 1}, key, secret)
        if r.get("status") == "OK":
            probs = r["result"]["problems"]
            ok_count += 1
            print(f"      [{cid}] OK  {len(probs)} 题 -> "
                  f"{[p['index'] for p in probs]}   {note}")
        else:
            print(f"      [{cid}] {r.get('status')}: {str(r.get('comment'))[:70]}   {note}")
        time.sleep(1.2)

    # 3) 结论
    print(f"\n[3/3] 结论")
    if ok_count == len(gyms):
        print("      密钥可以访问 Gym 题目列表 ✔")
        print("      => 可以做精确完成度：「本场 13 题，你解出 3 题」")
    elif ok_count:
        print(f"      仅 {ok_count}/{len(gyms)} 场可访问。")
        print("      => 可能只有你注册/参加过的 gym 才开放，需按场降级处理")
    else:
        print("      密钥无法访问 Gym 题目列表 ✘")
        print("      => 放弃精确分母，改为显示「已解出 N 题：A/D/F」")
    return 0


if __name__ == "__main__":
    sys.exit(main())
