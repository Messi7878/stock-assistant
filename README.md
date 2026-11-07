# A股 AI 股票账户助手

本地运行的 A 股「分析 + 提醒」工具。面向真实资金,当前**只做分析、提醒,不接自动下单**。

## 已实现(阶段 1–4)

- **数据底座**:实时行情 + 日线历史 K 线。东财 → 腾讯 → 新浪 三级回退,任一源被限流都会自动切换,不中断。
- **持仓管理**:手动录入持仓(代码/股数/成本),JSON 存储,自动算盈亏。
- **AI 分析**:均线 / MACD / RSI / 量能的技术面诊断 + 组合集中度、最大亏损等风险提示。**纯本地计算,离线可跑。**
- **提醒**:涨跌幅异动、放量、价格上破/下破触发。
- **网页仪表盘**:`python app.py` 启动,浏览器打开 http://127.0.0.1:8756,看行情/持仓/提醒/诊断,一键 AI 解读。
- **(可选)大模型解读**:`src/llm.py` 可把结构化诊断交给 DeepSeek 生成自然语言总结(需 API key)。

## 目录结构

```
stock-assistant/
├── app.py              # 网页仪表盘(python app.py)
├── main.py             # 命令行便捷入口(python main.py report)
├── config.json         # 自选股 + 提醒阈值/价格提醒 + 交易开关(默认关)
├── portfolio.json      # 持仓数据(自动生成)
├── secrets.json        # (可选)DeepSeek API key,已 gitignore
├── scripts/quote.py    # 命令行入口
├── web/index.html      # 仪表盘前端
└── src/
    ├── http.py         # 标准库 HTTP 封装(UA/重试/gzip)
    ├── data.py         # 行情 + K 线(多源回退)
    ├── portfolio.py    # 持仓管理
    ├── analysis.py     # 技术指标 + 诊断
    ├── plan.py         # 交易参考计划(支撑/压力/买卖区间/止损)
    ├── market.py       # 大盘环境(三大指数 -> 建议总仓位)
    ├── screen.py       # 每日推荐(榜单候选池 + 技术面打分)
    ├── allocation.py   # 总仓位与分散度建议(含行业集中度)
    ├── track.py        # 推荐胜率复盘
    ├── alerts.py       # 提醒(分级)
    ├── importer.py     # 券商导出 CSV/Excel 一键导入持仓
    ├── notify.py       # 推送(邮件/企业微信/钉钉/飞书/Server酱/PushPlus)
    ├── report.py       # 每日报告生成
    ├── llm.py          # 大模型解读(可选)
    └── broker.py       # 交易接口(预留,默认关闭)
```

## 快速开始

依赖仅 Python 标准库 + pandas/numpy(本机已装)。无需 pip。

```bash
cd stock-assistant
python app.py                        # 启动网页仪表盘 -> http://127.0.0.1:8756
python main.py quote                 # 查自选股实时行情
python main.py watch                 # 看自选列表
python main.py watch add 000858      # 加入自选
python main.py watch remove 000858   # 移出自选
python main.py report                # 持仓/自选诊断报告
python main.py check                 # 扫描异动/放量/价格提醒
python main.py analyze 600519        # 单股技术面诊断
python main.py plan 600519           # 交易参考:支撑/压力/买卖区间/止损
python main.py pick                  # 每日推荐(技术面筛选)
python main.py position              # 大盘环境 + 总仓位/分散度建议
python main.py orders                # 开盘前条件单参数(止损/止盈,复制到券商 App)
python main.py advice 600519         # 保守多因子定价(ATR波动/仓位/风险回报)
python main.py review                # 推荐胜率复盘(5/10 个交易日)
python main.py kline 600519 --limit 10
python main.py ai                    # DeepSeek 解读:买卖价位 + 分析(需配 key)
```

## 管理持仓

```bash
python main.py add 600519 100 1600 贵州茅台   # 手动录入:代码 股数 成本价 [名称]
python main.py import 持仓.csv                # 从券商 App 导出 CSV/Excel 一键导入
python main.py import 持仓.xlsx
python main.py portfolio                       # 看盈亏
python main.py remove 300750                   # 删除
```

> 导入支持 **CSV 和 Excel(.xlsx)**,需含「代码 / 持股数量」两列(名称、成本价
> 可选),常见中英文表头都支持;CSV 自动识别 utf-8 / gbk 编码,Excel 里数字型代码
> 会自动补前导零(如 `1` → `000001`)。示例表头:`证券代码,证券名称,持股数量,参考成本价`。

## 新闻面分析(可选)

`python main.py advice CODE` 会额外抓取该股的**近期公告 + 新闻**(东方财富),再交给 DeepSeek 判断是「利好 / 利空 / 中性」并给出理由和风险,用来在技术面之外做交叉验证。

```bash
python main.py advice 600403          # 技术面 + 新闻面 + AI 判断
python main.py advice 600403 --no-news # 只算技术面,不调 AI(省 token)
```

> 新闻/公告来自公开接口,可能延迟或缺失;AI 判断是定性参考,不是精确信号。

## 配置(config.json)

```json
{
  "watchlist": ["600519", "000001", "300750"],
  "account": { "total_capital": 6378.27 },   // 总资金(股票市值+现金),用于算仓位%
  "alert": {
    "enabled": true,
    "change_pct_threshold": 3.0,     // 涨跌幅超过 ±3% 提醒
    "critical_change_pct": 5.0,      // 超过 ±5% 判为"重要",置顶并加标题前缀
    "vol_spike_ratio": 2.0,          // 成交量为 20 日均量 2 倍提醒
    "price_alerts": []               // 例:[{"code":"600519","above":1300,"below":1200}]
  },
  "pick": { "enabled": true, "top": 5, "pool_size": 15 },
  "report": { "with_ai": true }
}
```

> `account.total_capital` 填上后,报告会给出「当前仓位 X% vs 建议仓位区间」和可用现金。

## 启用大模型解读(可选)

1. 设置环境变量 `DEEPSEEK_API_KEY`(或改 `src/llm.py` 里的 key)。
2. 在报告流程末尾调用 `llm.narrate(报告dict, api_key)` 即可得到中文解读。
   不填 key 时完全不依赖外部大模型,分析照常运行。

## 每日报告自动发手机

每天自动把「大盘与仓位建议 + 持仓盈亏 + 买卖参考 + 每日推荐 + 提醒 + AI 解读」推送到手机。

1. **选一个推送渠道**,编辑 `config.json` 的 `notify`:

| 渠道 | 需要填 | 说明 |
|------|--------|------|
| `wecom` | 群机器人 Webhook | 企业微信,最简单 |
| `dingtalk` | 群机器人 Webhook | 钉钉 |
| `feishu` | 群机器人 Webhook | 飞书 |
| `serverchan` | SendKey | 微信推送,免费额度 |
| `pushplus` | token | 微信推送,免费额度 |
| `email` | 邮箱 + SMTP 授权码 | 通用兜底 |

   把对应渠道的 `enabled` 改成 `true`,并填好地址/密钥;`notify.enabled` 也要改成 `true`。

2. **先手动测一次**(会真的推送到手机):
   双击 `推送测试.bat`(在 Windows 文件资源管理器里双击)。

3. **装定时任务**(每工作日 08:30 开盘前自动推送):
   双击 `安装每日推送.bat`。想改时间就编辑里面的 `08:30` 后重新运行。

命令行等价写法:

```bash
python daily_push.py     # 生成报告并推送一次
```

> 排查:手机没收到就看 `push.log`,里面记录了每个渠道的发送结果和错误原因。
> 短信推送需要接付费短信服务商,本项目未内置。

## 手机/异地访问(内网穿透)

仪表盘默认只监听 `127.0.0.1:8756`,手机在外面打不开。要随时随地用手机看:

1. **加密码**(已内置):`config.json` 里 `web.password` 非空时,打开仪表盘会要求登录——**用户名随便填,密码就是 `web.password`**。留空则不校验(仅建议本机使用时留空)。
2. **启动穿透**:在电脑上双击 `手机访问_启动穿透.bat`。窗口里会打印一个 `https://xxxx.lhr.life` 公网地址,并显示二维码,手机扫码直达。
3. 手机打开该地址 → 输入密码 → 即可。

> 关键前提:**电脑必须开机、那个黑窗口不能关**,否则手机打不开。
> 免费隧道每次重启**网址会变**(注册 localhost.run 并配置 SSH key 可固定子域名)。
> 网址 + 密码不要外传:虽然加了密码,但别人同时拿到两者就能看到你的持仓。

## 路线图

- [x] 阶段 1 数据底座(行情/K线/持仓)
- [x] 阶段 2 AI 分析(诊断/异动/风险)
- [x] 阶段 3 提醒(涨跌幅/放量/价格)
- [x] 阶段 4 网页仪表盘
- [x] 阶段 5 预留自动下单接口(src/broker.py,**默认关闭**,未接券商 QMT/Ptrade)

## 安全说明

- 自动交易默认**彻底禁用**:`config.json` 的 `trading.enabled=false`,且
  `src/broker.py` 未接入任何券商接口,所有下单调用都会被拒绝并抛错。
- 只有你开通券商程序化交易(QMT/Ptrade)并主动实现接口后,才可能启用。

## 免责声明

本工具仅供信息参考,不构成投资建议。数据来自公开行情接口,可能有延迟或缺失。
