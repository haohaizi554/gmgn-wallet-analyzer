# 数据字段

所有导出字段经过 `safe_export_value`。禁止 `None` / `null` / `NaN` / `""`。禁止把缺失写成 `0`。

## 字段状态

| status | 含义 | Excel 典型文案 |
|---|---|---|
| KNOWN | API 或可验证计算 | 数值 |
| ESTIMATED | 用当前供给等估算 | `$23.4K（估）` |
| NOT_APPLICABLE | 业务上不该有数字 | 不适用（转入获得） |
| API_MISSING | 接口没给 | GMGN 未提供 |
| UNKNOWN | 无法判断 | 未知来源 |
| ERROR | 请求失败 | 接口暂不可用 |

每个内部字段尽量带 `value / source / status / estimated / reason`。

## 代币分析表

| 列 | 内部字段 | 说明 |
|---|---|---|
| 币种 | symbol | 展示用，不是主键 |
| 代币合约 | token_address | 主键 |
| 来源平台 | source_platform | 见平台 fallback |
| 获得方式 | acquisition_type | BUY / TRANSFER_IN / BRIDGE / WRAPPED / … |
| 入场市值 | market_cap | 优先当时价格×当时供给 |
| 首笔买入 | first buy cost | 非 Buy 时为「不适用（转入获得）」 |
| 买入时间 | first acquisition ts | TransferIn 用首次转入时间 |
| 创建时间 | token_created_at | 不用 pool 时间冒充 |
| 时差 | first_acq - created | Transfer 标记「转入时间差」 |
| 已实现盈亏 | FIFO 或状态文案 | 与 GMGN 官方利润分列 |
| 总盈亏% | GMGN token 级若无则说明 | 不伪造 |

## 交易明细

Buy 的单笔盈亏固定为「未实现」。Sell 能匹配成本则给数字，否则「无法验证历史成本」。必须带 `token_address`。

## 特殊值

- 不适用（转入）
- 非 Launchpad
- 无法验证历史成本
- GMGN 未提供
- 接口暂不可用
- 未知来源
- 无可验证历史市值
