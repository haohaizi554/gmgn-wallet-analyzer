# API Mapping

Base URL：`https://openapi.gmgn.ai`  
认证：`X-APIKEY` + `timestamp` + `client_id`  
响应信封：`{ "code": 0, "data": ... }`，解析 `data`。

## 接口

| 用途 | 方法 | 路径 | Query / Body | Weight |
|---|---|---|---|---|
| 钱包流水 | GET | `/v1/user/wallet_activity` | chain, wallet_address, token_address?, cursor?, limit?, type[] | 3 |
| 钱包统计 | GET | `/v1/user/wallet_stats` | chain, wallet_address, period=7d\|30d | 3 |
| 钱包利润 | POST | `/v1/user/wallet_profits` | body: chain, period=1d\|7d\|30d\|all, wallet_addresses | 3 |
| Token 信息 | GET | `/v1/token/info` | chain, address | 1 |
| Token 池 | GET | `/v1/token/pool_info` | chain, address | 1 |
| 测连通 | GET | `/v1/user/info` | 无业务参数 | 2 |

不调用 `/v1/user/wallet_holdings`（需要私钥签名）。

分页：`data.activities` + `data.next`。`next` 为空即历史结束。First Buy **不得**只用报告窗口内的最早 Buy。

## Excel 字段 → 接口 → JSON → fallback → 是否估算

| Excel | 接口 | JSON | fallback | 估算 |
|---|---|---|---|---|
| 币种 | wallet_activity / token_info | token.symbol / symbol | 「未知」 | 否 |
| 代币合约 | wallet_activity | token.address | 跳过无地址记录 | 否 |
| 来源平台 | token_info → pool_info | launchpad_platform → launchpad → pool.exchange → pool_info.exchange → 特殊资产 | 「非 Launchpad」 | 否 |
| 获得方式 | wallet_activity | event_type/type | TransferIn / 特殊资产 / UNKNOWN | 否 |
| 首笔买入金额 | wallet_activity 完整历史 | cost_usd / price_usd×token_amount | 非 Buy：「不适用（转入获得）」 | 否 |
| 买入时间 | wallet_activity | timestamp 最小 Buy 或 TransferIn | GMGN 未提供 | 否 |
| 首买数量 | wallet_activity | token_amount | GMGN 未提供 | 否 |
| 入场市值 | activity + token_info | price_usd × total_supply（当时或当前） | 无可验证历史市值 | 当前供给时为是 |
| 创建时间 | token_info | creation_timestamp | GMGN 未提供（open/pool 另列） | 否 |
| 开盘时间 | token_info | open_timestamp | GMGN 未提供 | 否 |
| 池子创建时间 | token_info.pool / pool_info | creation_timestamp | GMGN 未提供 | 否 |
| 时差 | 本地 | first_acq - creation | 无法计算 | 否 |
| 持仓时长 | 本地 | 清仓：last_sell-first_acq；否则 now-first_acq | 无法计算 | 否 |
| 买入/卖出笔数 | wallet_activity 报告窗 | event_type | 0 仅当窗口内确实没有 | 否 |
| USD/SOL 金额 | wallet_activity | cost_usd / cost_sol\|quote_amount\|price×amount | GMGN 未提供 | SOL 由 quote 推算时为是 |
| Gas | wallet_activity | gas_usd / gas_sol | GMGN 未提供 | 否 |
| 单笔盈亏 | 本地 FIFO | Sell：proceeds-cost；Buy：未实现 | 无法验证历史成本 | 否 |
| GMGN 已实现/总盈亏 | wallet_profits | realized_profit / total_profit | 90d/自定义：「接口不支持该周期」 | 否 |
| 总盈亏% | wallet_profits | total_profit_pnl 或 total_profit/total_cost | 单 Token 无拆分则说明 | 否 |

不确定的字段不会猜测。原始响应当用户勾选时写入 `data/raw/<task_id>/`。
