# CLAUDE.md

给 AI 助手看的工作笔记。**这里只记「代价高、且从代码里看不出来」的东西**——
架构看 [README.md](README.md)，每处改动的来龙去脉看 [CHANGELOG.md](CHANGELOG.md)，
功能说明看 [使用说明.md](使用说明.md)。不要在这里复述它们，重复的内容会先过时。

---

## ⚠️ 本机环境的三个坑（都实际踩过）

1. **PATH 上的 `python` 是 msys2 版**（3.14，装了 Flask/requests），
   而 **Bash 工具里的 `/usr/bin/python` 没装依赖**——用它跑会报 `No module named 'flask'`。
   → 跑项目代码用 **PowerShell 工具 + `python`**；打包必须用 **`py -3`**（原生 CPython 3.11）。
   用 msys2 的 python 打出来的 exe 依赖 mingw DLL，换台机器跑不起来。
2. **测试命令加了管道就要过权限校验**（校验服务偶发不可用）。
   `settings.local.json` 白名单里有**不带管道**的原始形式，直接用它最稳：
   ```
   python tests/smoke_test.py          # 32 项，约 10 秒
   python tests/smoke_test.py --net    # 额外跑实网
   ```
3. **PowerShell here-string 会被中文引号 `“ ”` 拆断**。
   写 commit message 千万别用 `git commit -m @'...'@` 塞长文本——
   曾因此提交失败但标签却打上了，导致 tag 指向上一个 commit。
   → **长 message 一律写进文件再 `git commit -F <file>`**。

## 🌐 CF API 的反直觉行为（每条都是实测挖出来的）

| 行为 | 说明 |
|---|---|
| **Gym 榜单里的赛场队伍，`participantType` 是 `VIRTUAL` 而非 `CONTESTANT`** | 按类型筛会得到「0 支正式队伍」，必须认 `party.ghost` 字段。差点据此误判功能做不了 |
| **`showUnofficial=false` 对 Gym 返回 0 行** | 没法只取正式队伍，只能整份榜单拉下来自己筛（南京 2024 共 3136 行、3MB） |
| **签名只对 Gym 有效** | 非 Gym 比赛带签名反而被拒：`Non-gym contest standings ... only via anonymous GET`。一律签名或一律匿名都会漏掉一半 |
| **Gym 题目有题名，但没有 rating / tags** | 所以 ICPC 页的难度只在官方赛显示 |
| **`user.status` 包含 Gym 提交** | 这是「历年区域赛做过的题能自动对上」的前提 |
| **`DIFFICULTY_BANDS` 最高档 `max=9999` 不是题目难度上限** | 题库实测只到 3500（`MAX_PROBLEM_RATING`）。拿 9999 去算深链会得到 0 题 |

## 💸 昂贵操作（别手滑触发）

| 操作 | 代价 |
|---|---|
| ICPC 题单抓取 | 约 1.5 秒/场 × 160 ≈ **4 分钟** |
| ICPC 奖牌线抓取 | 约 4 秒/场 × 151 ≈ **10 分钟**，下行 ~500MB |
| `problemset.problems` 全量题库 | 单次约 10 秒，进程内只加载一次 |
| `contest.list?gym=true` | 单次约 17 秒，2599 场 |

抓取结果都**永久缓存**在 `data/`，且每 10 场增量落盘。改奖牌比例**不需要重抓**——
缓存里存的是解题数分布，`medal_lines()` 在渲染时才算。

## 🔒 绝不能提交 / 分发的文件

- **`data/cf_api.json`** —— 本机存着**真实的 CF API 密钥**。`.gitignore` 已用 `data/*.json` 覆盖。
- `data/cf_army.json`、`data/cf_todo.json` —— 用户个人数据。
- **打包 Release 前必须逐字节扫描 exe 与 zip**，确认密钥字符串零命中。
  exe 里的字符串是**明文可提取的**——这也是反馈页坚决不内置 GitHub token 的原因。

可以随 Release 分发的：`cf_icpc_contests.json` / `cf_icpc_problems.json` / `cf_icpc_medals.json`
（通用数据，让队友开箱即用，省掉 14 分钟抓取和申请密钥）。

## 🧭 代码地图（找东西时看这里，别全量读）

```
cfhelper/
  config.py    所有常量与阈值。改行为先看这里，多半有现成开关
  paths.py     路径解析 + read_json / atomic_write_json（原子写，防硬退出写坏文件）
  cf_api.py    唯一出网层：信号量限流、TTL+容量缓存、限流退避、API 签名
  analysis.py  纯计算：等级/预测/训练计划/弱点墙/推荐/团队/对比/热力图
  icpc.py      ICPC 比赛库：四档分类、完成度合并、抽取、奖牌线
  army.py todo.py contests.py   本地数据 + 比赛日历
  routes.py    编排与渲染 + 心跳 + 同源守卫
```

**`analysis.py` 与 `icpc.py` 是纯函数**，可脱网直接测——32 项冒烟测试全离线跑得动。

## 🛠️ 本项目的工作约定

- **实测优先于假设**。这个项目里几乎每个非平凡改动都先写探测脚本验证再动手
  （放 scratchpad，不进仓库）。CHANGELOG 里带的数字都是实测值，不是估算。
- **规则写成纯函数 + 测试守护**，不要塞进模板或 JS。
  奖牌线、抽取规则、弱点墙都是这么做的。
- **每个改动配套**：CHANGELOG 条目 → 版本号（`config.py` / `build.bat` / README / 使用说明 **四处**）→ tag → Release。
- **文档里的历史条目不要改**。CHANGELOG 旧版本记的是当时的事实，改了就是篡改历史。
- 提交前跑 `python tests/smoke_test.py`。

## 📌 当前状态（v2.17）

- 7 个页面：首页 / 刷题器 / ICPC / 组队作战 / 对比 / 题单 / 反馈
- 32 项冒烟测试全过；仓库公开，GPL-3.0；Release 带可下载 exe
- **已知遗留**：首页「数据总览」表格与详情卡有重复（改单人后留着主要为 CSV 导出）；
  ICPC 行末 `Gym/官方` 标记除了解释「为何没有题目总数」外用处不大
