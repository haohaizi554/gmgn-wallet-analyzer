# Stability v3 报告

日期：2026-09-17

## Before（真实事故，logs/app.log 17:16–17:18）

钱包 `9P9aAh3kdMK651CcDG4iCdoByYj1FJgKq3yVoPrXVCAu`，Key #1 `****3cfc`：

- wallet_activity 第 1–21 页 HTTP 200
- 第 22 页 HTTP 429，cooldown ≈ 27s
- 复位时刻一到立刻同 Key 再打 → 429
- 再立刻 retry → `RATE_LIMIT_BANNED`
- 当前钱包 **FAILED**
- JobEngine **立刻** 启动下一钱包 `wallet_stats` / `profits` / `activity`，继续撞 ban

根因：全局共用 limiter、`_request` 内 sleep 后同 Key 重试、无 reset 安全裕量、429 当普通失败、下一钱包不继承 Key 冷却、Job 启动 `limiter.reset()`、多钱包共用 `task_id`。

## After（本轮实现 + 真实 50 页验证）

实现要点：

- 每个 API Key 独立 `WeightedRateLimiter`
- `CredentialScheduler` 选 Key；429 标记 `RATE_LIMITED` 后退出本次 HTTP，由调度器换 Key 或等待
- `RATE_LIMIT_RESET_SAFETY_MARGIN` 默认 3s（日志可见 `reset=17:55:32` → `effective_resume=17:55:35`）
- `BANNED` vs `THROTTLED`；cooldown 期间该 Key HTTP=0
- 全部 Key 冷却时钱包 `WAITING_API`，Job 不失败
- `GlobalSafetyController`：10s 内 ≥2 Key 且 reset ±5s → `GLOBAL_COOLDOWN`
- `job_id` / `wallet_task_id` 分离；raw JSON 使用 uuid；429 metrics 不双计
- Job 启动不再 `limiter.reset()`
- GUI：单一「分析任务」页，删除独立「任务进度」

### 真实 API：同一事故钱包，50 页 wallet_activity

脚本：`scripts/stability_v3_benchmark.py`  
结果：`logs/stability_v3_benchmark.json`

| 指标 | 数值 |
|---|---|
| 钱包 | `9P9a...VCAu` |
| Key 数量 | 1（`Key #1 ****3cfc`） |
| wallet_activity 页数 | **50** |
| 总耗时 | 97.94 s |
| pages/min | 30.63 |
| 总 HTTP 请求 | 53 |
| 每 Key 请求数 | Key #1 = 53 |
| 每 Key 429 | Key #1 = **2** |
| metrics.total_429 | **2**（与 rate_limit_events 一致，无双计） |
| Global cooldown | 0（单 Key，模式仍为独立 Key） |
| 结束 adaptive utilization | 0.75（配置最大目标 75%） |
| 平均 HTTP（含调度等待的外围计时） | 1.959 s |
| 服务端延迟 EWMA | ~0.46–0.57 s |
| local_rate_wait | 22.88 s |
| credential_wait / cooldown_wait | 43.3 s |
| 钱包 FAILED？ | **否**，50 页全部完成 |
| 下一钱包撞 ban？ | **否**（任务在冷却后继续同一分页） |

第 14 页附近仍出现 2 次 429（本地 5w/s 模型无法 100% 拟合 GMGN）。与事故对比：

- 不再在 `reset_at` 整点立刻连打
- 第二次请求等到 `effective_resume`（+3s）
- 没有把钱包打成 FAILED
- 没有开启下一个钱包继续轰炸
- 冷却结束后任务继续翻页到 50

单 Key 环境下无法「切换备用 Key」。若配置多把 Key，调度器会把后续请求打到 HEALTHY Key。

## P0 Bug 修复

| 问题 | 状态 |
|---|---|
| task_id 覆盖多钱包 | 已修：`job_id` + `wallet_task_id=JOB:wallet`；`jobs` / `wallet_tasks` / `wallet_reports` |
| limiter.reset 清掉 429 cooldown | 已修：Job 开始不再 reset；设置页改 Key 才重建 pool |
| Key 分配 17/17/66 | 已修：score = wait + inflight + latency + RR；300 请求测试 25%–40% |
| raw JSON glob+1 并发覆盖 | 已修：`uuid4` 文件名；100 线程 100 个不同文件 |
| 429 metrics 双计 | 已修：HTTP 429 只 `record` 一次；cooldown 记 `rate_limit_events` |
| 批量不公平（A 全部完成才 B） | 已修：多钱包并行 + Token 进度交叉；RR 顺序测试 |
| GUI 钱包分析 / 任务进度重复 | 已修：导航「分析任务」；删除独立任务进度页 |

## 测试

`python -m unittest discover -s tests -q`

**50 passed**（原 34 + v3 新用例，未删旧 First Buy / FIFO / stale history / Excel 用例）

## 验收对照

- 一个 Key 一个 limiter
- Key cooldown 跨 Job 保留
- Job 启动不 reset limiter
- cooldown 期间不向该 Key 发 HTTP（单测 banned key call_count=0）
- BANNED 不在 `_request` 内死循环同 Key sleep-retry
- 备用 HEALTHY Key 可接管
- 全部 Key 冷却 → WAITING_API 而非 FAILED
- 多 Key 同时 429 → GLOBAL_COOLDOWN
- reset 安全裕量 ≥ 3s
- Credential 分配均衡
- task_id 不再互相覆盖
- raw JSON 并发无覆盖
- 429 metrics 不双计
- 单钱包与批量同一 AnalysisPage / JobEngine
- 「任务进度」独立页面删除
- First Buy / SQLite 增量缓存 / Excel 0 空测试继续通过
- 真实 API 完成 50 页 wallet_activity，无 FAILED、无连续撞 ban 风暴
