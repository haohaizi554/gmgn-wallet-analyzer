# V3 稳定性审计

日期：2026-09-17。以源码 + `logs/app.log` 17:16–17:18 事故为准。

## 真实事故时间线

钱包 `9P9a...`，Key #1 `****3cfc`：

| 时间 | 事件 |
|---|---|
| 17:16:55 | stats/profits 200 |
| 17:16:56–17:17:40 | wallet_activity 第 1–21 页 200，约 1s/页，`rate_wait=0.00` |
| 17:17:41 | 第 22 页 **429**，cooldown 27.1s `reset_at=1789636688` |
| 17:18:09 | **同 Key 立刻再打 activity → 429**，cooldown 10.3s |
| 17:18:20 | 再 429 → `RATE_LIMIT_BANNED`，钱包 **FAILED** |
| 17:18:20 | JobEngine **立刻** 下一钱包 `wallet_stats` |
| 17:18:24–17:18:35 | stats 连续 429 |
| 17:18:44–17:18:55 | profits 连续 429，继续 activity |

根因全部可在源码对应：

1. **一个全局 limiter**（`CredentialPool` 文档写明「不增加额度」）。多 Key 无法隔离 429。
2. **`GMGNClient._request` 内部 429 循环**：sleep 到 `reset_at`（无安全裕量）后 **同 Key 再试**，最多 `max_429_retries=2`，第三次 raise。日志 27s → 立刻 429 完全符合。
3. **`set_server_cooldown` 再 `metrics.record(0, status=429)`**，HTTP 侧已 record 一次 → 429 双计。
4. **JobEngine 把任意 Exception 标 FAILED** 然后 for 循环下一钱包；`wallet_stats` 失败只 warning 后继续 profits/activity。
5. **`analysis_page.start_analysis` 调用 `self.app.limiter.reset()`**，会清掉跨 Job cooldown（本事故是同一 Job 内，但属于 P0）。
6. **所有钱包 `req.task_id = job_id`**，`task_runs.task_id` / `wallet_reports.id` 主键互相覆盖。
7. **raw JSON**：`len(glob)+1` 并发可撞号。
8. **调度**：`last_used_at` sort + `rr % len` 叠加，易 17/17/66。
9. **无 min-spacing**：weight=3 只要 bucket 有 token 就发；HTTP~0.8s 时本地 `rate_wait=0`，服务端窗口仍可能满。
10. **GUI**：钱包分析 + 任务进度两套入口。

## 将修改的模块

| 模块 | 改动 |
|---|---|
| `app/api/credential_pool.py` | 每 Key 独立 limiter；RATE_LIMITED/BANNED |
| `app/api/scheduler.py` **新建** | CredentialScheduler + GlobalSafetyController |
| `app/api/rate_limiter.py` | 安全裕量、min-spacing、429 不计双次、初始 60% 爬升 |
| `app/api/gmgn_client.py` | 禁止同 Key 内死循环 429；退回 Scheduler |
| `app/api/metrics.py` | 分 local/credential/cooldown wait；rate_limit_events |
| `app/api/exceptions.py` | RateLimitSeverity THROTTLED/BANNED |
| `app/jobs/engine.py` | wallet_task_id；WAITING_API；公平 Token 队列；不 reset limiter |
| `app/jobs/models.py` | WAITING_API 等状态 |
| `app/storage/database.py` + `migrations.py` + `repositories.py` | jobs / wallet_tasks / reports 分离 |
| `app/services/wallet_analysis_service.py` | 独立 raw 文件名；wallet_task_id；可拆 prepare/token |
| `app/gui/*` | 合并为「分析任务」；删除任务进度导航 |
| `app/config.py` / `.env.example` | KEY_RATE、INITIAL_UTILIZATION、RESET_SAFETY_MARGIN |

## 数据库 migration

保留 `wallet_reports`，新增/规范：

```
jobs(job_id PK, ...)
wallet_tasks(wallet_task_id PK, job_id, wallet_address, state, ...)
wallet_reports.id = report_id（不再等于 job_id）
  + job_id, wallet_task_id
```

旧行：`wallet_task_id = id`，`job_id = id`。`task_runs` 继续可用但写入 `wallet_task_id`。

## 429 状态机

```
HTTP 429 / RATE_LIMIT_*
  → 该 Key state=RATE_LIMITED（BANNED 若 body 含 RATE_LIMIT_BANNED/ban）
  → cooldown_until = reset_at + safety_margin(默认 3s)
  → 该 Key 在 cooldown 前 0 HTTP
  → 请求退回 Scheduler
  → 其它 HEALTHY Key 且 limiter 允许 → 换 Key
  → 全部冷却 → Wallet WAITING_API，Job 保持 RUNNING
  → 10s 内 ≥2 Key 429 且 reset ±5s → GLOBAL_COOLDOWN（共享限制嫌疑）
Job.start 禁止 limiter.reset()
```

## 新 GUI

导航：分析任务 | 历史记录 | 数据导出 | 系统设置 | 关于

分析任务单页：左输入（自动单钱包/批量）+ 右 Job 摘要 / Key 卡 / 钱包表 / 选中钱包 Tabs。
