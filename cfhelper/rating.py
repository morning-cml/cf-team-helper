# -*- coding: utf-8 -*-
"""Codeforces 官方涨分算法 + 队伍综合 rating。纯函数、零依赖，可脱网测。

算法出处
--------
Mike Mirzayanov 公开的实现（https://codeforces.com/contest/1/submission/13861109），
照 TLE 的 `rating_calculator.py` 与 carrot 的 `predict.js` 翻写——这两个是社区里
公认对得上官方结果的实现。四步：

    seed(r)   = 1 + Σ 全场每个人战胜 r 的概率      （r 的期望名次）
    midRank   = √(实际名次 × seed)
    needRating= 让 seed 等于 midRank 的那个 rating
    delta     = (needRating − rating) / 2  向零取整

为什么不用 FFT
--------------
TLE / carrot 都用 FFT 一次算出整条 seed 曲线，因为它们要给**全场上万人**同时算 delta。
本项目只给**一个人**算：seed 只需在二分经过的十几个 rating 上求值，每次 O(不同 rating 数)
≈ 2000 次乘加，加记忆化后一次预测不到 1 毫秒。犯不上为此引入 numpy——
打包体积会多几十 MB，而 exe 是要发给队友的。

精度（实测，回归用例见 tests/fixtures/）
--------------------------------------
拿真实比赛的 contest.ratingChanges 当标准答案（它同时给了输入 rank+oldRating
和标准答案 newRating−oldRating），对**打过 ≥16 场的老选手**：

    Div.2   误差中位  0   平均绝对 3.2   ±10 内 98%
    Div.3   误差中位 +7   平均绝对 7.1   ±10 内 95%
    Global  误差中位 −3   平均绝对 5.9   ±10 内 91%

**新号误差大得多**（2-3 场的账号中位差 +98）：CF 对参赛场次少的账号有加速收敛的处理，
不在公开算法里。本工具面向有比赛历史的队友，这个偏差不影响使用，但别拿它去解释新号的涨分。
"""
from . import config


def _intdiv(x, y):
    """向零取整的整除——CF 用的是这个，负数上和 Python 的 // 不一样。"""
    return -(-x // y) if x < 0 else x // y


def elo_win_prob(ra, rb):
    """rating 为 ra 的选手战胜 rating 为 rb 的选手的概率。"""
    return 1.0 / (1.0 + 10.0 ** ((rb - ra) / 400.0))


class Field:
    """一场比赛的参赛者 rating 分布。构造一次，可反复算 seed / delta / 表现分。

    hist: {rating: 人数}。首次参赛者（CF 给 oldRating=0）应由调用方折算成
    config.UNRATED_IN_FIELD 再传进来——按字面的 0 分算会把整个场次判弱，
    实测会让所有人的 delta 系统性偏高十几分。
    """

    def __init__(self, hist):
        self.items = sorted((int(r), int(c)) for r, c in hist.items() if int(c) > 0)
        self.size = sum(c for _, c in self.items)
        self._memo = {}

    def seed(self, r):
        """rating 为 r 的选手的期望名次 = 1 + 全场每个人战胜他的概率之和。"""
        v = self._memo.get(r)
        if v is None:
            s = 1.0
            for q, c in self.items:
                s += c / (1.0 + 10.0 ** ((r - q) / 400.0))
            self._memo[r] = v = s
        return v

    def seed_excluding(self, r, own_rating):
        """把「自己」那一份从期望名次里摘掉。

        算某人的 delta 时，他自己也在直方图里，得先减掉自己对自己的那份胜率，
        否则每个人的期望名次都被自己垫高了 0.5。
        """
        return self.seed(r) - elo_win_prob(own_rating, r)

    def rank_to_rating(self, rank, own_rating):
        """反解：期望名次正好是 rank 的那个 rating。

        两处防呆，都是踩过的：
        - **rank 至少按 1 算**。第 1 名且自己远强于全场时 midRank 会算出 0.7，
          而期望名次不可能小于 1，二分找不到交点会一路顶到上界。
        - **上界卡在现实分段内**（RATING_SEARCH_MAX）。seed 在远高于全场的区间已经压平到 1，
          此时"减掉自己"那一项反而成了主导，seed_excluding 不再单调，
          二分在那段会返回垃圾值——实测能让 delta 从 +48 跳到 +2298。
        """
        rank = max(1.0, rank)
        lo, hi = 1, config.RATING_SEARCH_MAX
        while hi - lo > 1:
            mid = (lo + hi) // 2
            if self.seed_excluding(mid, own_rating) < rank:
                hi = mid
            else:
                lo = mid
        return lo

    def raw_delta(self, rank, rating):
        """未加常数修正的原始 delta。"""
        seed = self.seed_excluding(rating, rating)
        mid_rank = (rank * seed) ** 0.5
        need = self.rank_to_rating(mid_rank, rating)
        return _intdiv(need - rating, 2)

    def delta(self, rank, rating):
        """rating 为 rating 的选手拿到第 rank 名时的涨跌分。

        末尾那个常数是官方两步修正的实测等价值：官方那两步要先算出**全场每个人**的
        delta 才能求和，而全场里有大量新号——它们的真实 delta 被 CF 另行加速过，
        照公开算法算出来的和是错的，据此求出的修正自然也错（实测能差到 −27）。
        直接用真实比赛回归出这个常数，比强行还原那两步更准（见模块开头的实测数据）。
        """
        return self.raw_delta(rank, rating) + config.RATING_CALC_CONST

    def performance(self, rank):
        """拿到第 rank 名相当于什么水平 —— 即「delta 恰好不再为正」的那个 rating。

        名次越靠前，表现分越高。顶端会被 RATING_SEARCH_MAX 截断：
        第 1 名在任何现实分数下都涨分，本来就没有让它不涨的 rating。
        """
        lo, hi = config.RATING_SEARCH_MIN, config.RATING_SEARCH_MAX
        if self.delta(rank, hi) > 0:
            return hi
        while hi - lo > 1:
            mid = (lo + hi) // 2
            if self.delta(rank, mid) > 0:
                lo = mid
            else:
                hi = mid
        return hi


# ==================== 队伍综合 rating ====================
def compose_team_rating(ratings):
    """一支队伍相当于多少分的个人 —— CF 官方口径（TLE 的 composeRatings）。

    定义：二分找出这样一个 r，使得「rating 为 r 的人**同时**打赢队里每一个人」的
    概率恰好是 50%。人越多、越强，这个 r 越高，符合直觉：三个 1600 的人组队，
    要一个人打赢他们仨才算平手，那人得明显强于 1600。

    ratings: [int, ...]，空列表返回 None。
    """
    rs = [int(r) for r in ratings if r]
    if not rs:
        return None
    lo, hi = -100.0, 10000.0
    for _ in range(40):
        mid = (lo + hi) / 2.0
        p = 1.0
        for r in rs:
            p *= elo_win_prob(mid, r)
        if p < 0.5:
            lo = mid
        else:
            hi = mid
    return round((lo + hi) / 2)
