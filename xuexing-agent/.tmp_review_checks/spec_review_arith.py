"""独立算术探针：仅用 specs/drafts/diagnosis.spec.md 写明的【参考】公式，
复算规格自报的探针值，检验"下行折价"到底是单次应用还是逐轮应用。"""

def clamp01(x):
    return 0.0 if x < 0 else (1.0 if x > 1 else x)

def slip(d):  # spec §3.1 【参考】 clamp01(0.05 + 0.20*difficulty)
    return clamp01(0.05 + 0.20 * d)

G = 0.1  # 填空题默认 guess（规格例4、conftest 注释一致）

def update(prior, lrs):  # odds 乘法更新（spec §3.2 步骤2）
    odds = prior / (1 - prior)
    for lr in lrs:
        odds *= lr
    return odds / (1 + odds)

# 例2 / I8: b1(0.3), b2(0.6) 全对 -> b
m_b = update(0.5, [(1 - slip(0.3)) / G, (1 - slip(0.6)) / G])
# I8(c): a1(0.2), a2(0.5) 全错 -> a
m_a = update(0.5, [slip(0.2) / (1 - G), slip(0.5) / (1 - G)])
f = 0.4 + 0.6 * m_a  # 下行折价因子

print("m_b (b 两对)      =", round(m_b, 6), " 规格声称 0.986644")
print("m_a (a 两错)      =", round(m_a, 6), " 规格声称 0.016393")
print("折价因子 f        =", round(f, 7))
print("单次折价 b        =", round(m_b * f, 6))
print("两次折价(2轮) b   =", round(m_b * f * f, 6), " 规格声称 0.165722")
# 例2 上行补证
print("fill a = max(0.5, 0.6*m_b) =", round(max(0.5, 0.6 * m_b), 6), " 规格声称 0.591986")
# 例1: a1 对 + a2 错
m_ex1 = update(0.5, [(1 - slip(0.2)) / G, slip(0.5) / (1 - G)])
print("例1 a             =", round(m_ex1, 6), " 规格声称 0.602649")
# 空responses prior 与 6位舍入的冲突
print("round(0.123456789, 6) =", round(0.123456789, 6), " != prior 0.123456789")
# 夹具内 1-s 与 g 的最小组合（验证 +0.05 分支不被触达）
print("min(1-s) over fixtures =", 1 - slip(0.8), " max(g) =", 0.25)
