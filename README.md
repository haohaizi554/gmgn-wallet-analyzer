# GMGN 钱包链上分析工具

Windows 桌面程序：输入一个或多个 Solana 钱包地址，选择时间范围，通过 **GMGN OpenAPI** 拉取交易和 Token 数据，分析真正的首次买入、来源平台、时差、盈亏与 Gas，并导出 Excel / JSON。

核心原则：**准确、完整、可解释、可恢复、Excel 0 空字段**。Token 主键永远是 `(chain, token_address)`，禁止用 symbol 关联。

## 1. 项目用途

给运营/投研对照 GMGN 页面核对钱包：

- 报告周期内涉及哪些 Token
- 每个 Token 的**完整历史 First Buy**（不是周期内第一笔）
- 无 Buy 时识别 TransferIn / Bridge / Wrapped / xStocks
- GMGN 官方利润 + 本地 FIFO 对账（两套数字分开）
- 异常/缺失字段可审计

## 2. Python 版本

Python **3.12+**（当前开发环境可用 3.13）。

## 3. 安装依赖

```bat
pip install -r requirements.txt
```

## 4. 申请 API Key

1. 打开 [GMGN](https://gmgn.ai) 申请 OpenAPI Key。
2. 本工具**只需要** `GMGN_API_KEY`。
3. **不要**填写区块链钱包私钥。不调用 `wallet_holdings`。

## 5. .env 配置

```bat
copy .env.example .env
```

编辑 `.env`：

```
GMGN_API_KEY=你的key
GMGN_API_KEYS=key1,key2
GMGN_API_BASE=https://openapi.gmgn.ai
GMGN_PLAN=Free
GMGN_RATE_LIMIT_RATE=5
GMGN_RATE_LIMIT_CAPACITY=5
GMGN_TARGET_UTILIZATION=0.80
GMGN_API_WORKERS=4
```

多把 Key 只用于故障切换（401/403），**全部共用一个全局加权令牌桶**。3 把 Free Key ≠ 15u/s，仍然是 5u/s × 80% ≈ 4 weighted units/s。也可在 GUI「系统设置」里填写并点「测试连接」。`.env` 已加入 `.gitignore`。

## 6. 启动

```bat
python main.py
```

窗口约 1500×920，最小 1200×760。

## 7. GUI 功能

| 页面 | 说明 |
|---|---|
| 钱包分析 | 多行地址；1 个=单钱包，>1=批量。同一 JobEngine |
| 任务进度 | 同一套任务的另一入口，按 job_id 路由，不串台 |
| 历史记录 | Job + 单钱包报告，打开 Excel/JSON |
| 数据导出 | 打开 output 目录 |
| 系统设置 | 多 API Key、目标利用率 60/80/90%、Workers、测试连接 |
| 关于 | 版本与数据原则 |

主线程不发 HTTP。点「停止」设置 Event，限流等待可立即退出。不同 Token 可并行，同一 Token 的 cursor 链保持串行。

## 8. Excel 字段说明

至少 5 个 Sheet：代币分析、交易明细、异常与补全、采集范围、原始概要。

详见 `docs/data-fields.md`。列冻结、筛选、自动列宽、盈亏红绿字体。地址可缩写展示，完整值在单元格或 JSON 中。

## 9. 数据来源

见 `docs/api-mapping.md`。官方字段以 [GMGN OpenAPI](https://github.com/GMGNAI/gmgn-skills) 为准。

## 10. 特殊值含义

| 文案 | 含义 |
|---|---|
| 不适用（转入获得） | 没有 Buy，首次获得是转入 |
| 非 Launchpad | 平台链路上没有任何 launchpad/pool exchange |
| 无法验证历史成本 | Sell 匹配不到完整 Buy 成本 |
| GMGN 未提供 | 接口该字段为 null |
| 接口暂不可用 | 请求失败 |
| $xx（估） | 用当前供给估算入场市值 |
| 接口不支持该周期 | 90d/自定义没有官方 profits 周期 |

## 11. Free API 限流

全局加权令牌桶，默认服务端 `rate=5, capacity=5`，目标利用率 80% → 有效约 4 weighted units/s。`wallet_activity/stats/profits` weight=3，`token_info/pool` weight=1。有限并发（默认 4 workers）只重叠网络等待，不叠加额度。429 触发全局冷却，禁止切备用 Key 绕过。状态栏显示实际使用率，不是写死的 80%。

## 12. 常见错误

- **401**：API Key 无效，或 timestamp 偏差超过约 ±5 秒。
- **403**：权限 / IP / 本机走了 IPv6。请改用 IPv4。
- **地址红色**：不是 Solana Base58（32–44）。
- Token 失败只标记该 Token，其它继续。

## 13. 429 说明

读取 `X-RateLimit-Reset` 或 JSON `reset_at`，等到该时刻再重试，同一请求最多 2 次。冷却期间继续打点会把 ban 每次延长约 5 秒，最长约 5 分钟。日志会出现 `RATE_LIMIT 等待 GMGN API 限频恢复`。

## 14. 数据准确性说明

- First Buy 按 **token 完整 cursor 历史** 的最小 timestamp，不是报告窗口内第一笔。
- 「每钱包交易上限」只限制报告窗口流水，不限制 First Buy 追溯。
- GMGN `wallet_profits` 只支持 1d/7d/30d/all。90 天和自定义周期不会伪造官方 PnL。
- 官方利润与本地 FIFO 分列，避免混成一个数。
- Token 创建时间、开盘时间、池子创建时间分列，不用池子时间冒充创建时间。
- 同名币（例如多个 ZEC mint）按合约隔离。

## 测试

```bat
python -m unittest discover -s tests -v
```
