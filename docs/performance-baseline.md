# 性能基线（优化前）

来源：2026-09-17 真实运行日志 + 源码调度模型。

## 调度

- Worker：1 条线程，Token 串行
- HTTP：同步，limiter acquire 后再 request，返回后才下一个
- wallet_activity weight=3，Free server rate=5 → 理论上限 ≈1.67 req/s
- 实测 RTT 约 2–3s/页 → **实际 ≈0.3–0.5 activity req/s**
- 估算加权利用率：`0.4 req/s × 3 weight ≈ 1.2 weight/s / 5 ≈ 24%`

## 一次真实采集观察

日志形态：

```
采集钱包流水 第 1..N 页   （约 2–3 秒/页）
Token i/N 追溯完整历史 第 1..K 页
token_info + pool_info 每个 Token 再 2 次
```

若报告窗约 50 页流水 + 大量 Token 历史，冷启动可达数分钟到十几分钟。

## 优化目标

| 指标 | 基线 | 目标 |
|---|---|---|
| 加权利用率 | ~20–25% | 长期 70–85%，均值约 80% |
| 并发 | 1 in-flight | 2–8 worker，cursor 链仍串行 |
| 二次运行 | 完整重翻历史 | 增量 + Token Info 缓存 |
| 429 | 少 | 不靠切 Key 绕过；偶发后自适应降速 |

正确性优先：Token/Trade 数量不得无解释少于旧版。
