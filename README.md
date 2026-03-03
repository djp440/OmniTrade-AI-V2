# OKX多Agent自动交易机器人

基于多Agent架构的OKX自动交易机器人，使用OpenAI GPT-4o进行技术分析和交易决策。

## 功能特性

- **自主OKX客户端**：完全基于aiohttp自主实现，不依赖第三方OKX SDK
- **多Agent架构**：
  - 分析师(Analyst)：分析K线图并给出交易建议
  - 交易员(Trader)：将分析转换为具体交易指令
  - 压缩者(Compressor)：压缩分析结果用于历史记录
- **事件驱动**：基于OKX WebSocket K线收盘事件触发分析
- **风险控制**：支持止损止盈、仓位管理、单笔风险控制
- **黑白K线图**：生成符合文档要求的黑白风格K线图

## 项目结构

```
.
├── config/
│   ├── config.toml      # 程序配置
│   └── prompt.toml      # Agent Prompt配置
├── doc/
│   └── 开发文档.md       # 详细开发文档
├── logs/                # 日志目录
├── src/
│   ├── application/     # 应用层
│   │   ├── bootstrap.py     # 启动自检
│   │   └── trading_loop.py  # 主事件循环
│   ├── domain/          # 领域层
│   │   └── models.py        # 领域模型
│   ├── infrastructure/  # 基础设施层
│   │   ├── config_loader.py # 配置加载
│   │   ├── llm_client.py    # LLM客户端
│   │   ├── logger.py        # 日志组件
│   │   ├── okx_client.py    # OKX客户端
│   │   └── utils.py         # 工具函数
│   └── services/        # 服务层
│       ├── agent_service.py    # Agent调度
│       ├── history_service.py  # 历史记录管理
│       ├── kline_service.py    # K线服务
│       └── trade_service.py    # 交易服务
├── .env                 # 环境变量（需自行创建）
├── .env.example         # 环境变量示例
├── main.py              # 主程序入口
├── requirements.txt     # Python依赖
└── README.md            # 本文件
```

## 快速开始

### 1. 环境要求

- Python >= 3.10
- 2核CPU、2G内存（最低配置）

### 2. 安装依赖

```bash
# 创建虚拟环境
python -m venv venv

# 激活虚拟环境
# Windows:
venv\Scripts\activate
# Linux/Mac:
source venv/bin/activate

# 安装依赖
pip install -r requirements.txt
```

### 3. 配置环境变量

复制 `.env.example` 为 `.env`，并填写你的API密钥：

```bash
cp .env.example .env
```

编辑 `.env` 文件：

```env
# OKX 实盘密钥（实盘交易时使用）
OKX_REAL_API_KEY=your_real_api_key
OKX_REAL_API_SECRET=your_real_api_secret
OKX_REAL_PASSPHRASE=your_real_passphrase

# OKX 模拟盘密钥（建议先用模拟盘测试）
OKX_DEMO_API_KEY=your_demo_api_key
OKX_DEMO_API_SECRET=your_demo_api_secret
OKX_DEMO_PASSPHRASE=your_demo_passphrase

# OpenAI API密钥
OPENAI_API_KEY=sk-your_openai_api_key
OPENAI_BASE_URL=https://api.openai.com/v1  # 可选，用于代理
```

### 4. 配置交易对

编辑 `config/config.toml`：

```toml
[global]
demo_mode = true              # true使用模拟盘，false使用实盘
log_level = "INFO"
log_dir = "./logs"
max_analysis_history_length = 10
k_line_count = 100
llm_model = "gpt-4o"
trade_record_path = "./trade_records.csv"
td_mode = "isolated"          # isolated逐仓 / cross全仓
risk_per_trade = 0.01         # 单笔风险1%

[[trade_pairs]]
inst_id = "BTC-USDT-SWAP"
timeframe = "1H"              # K线周期: 1m/5m/15m/1H/4H/1D
leverage = 10
position_size = 100           # 开仓名义金额（USDT）
stop_loss_ratio = 0.02        # 止损比例2%
take_profit_ratio = 0.05      # 止盈比例5%
```

### 5. 运行程序

```bash
# 确保虚拟环境已激活
python main.py
```

## 交易指令类型

支持7种交易指令：

1. **entry_long** - 市价开多仓，附带止盈止损
2. **entry_short** - 市价开空仓，附带止盈止损
3. **close_position** - 全平并自动取消止盈止损
4. **change_stop** - 修改止损价格
5. **change_profit** - 修改止盈价格
6. **exit_long** - 仅减仓（多仓），不平仓
7. **exit_short** - 仅减仓（空仓），不平仓

## 启动自检流程

程序启动时会自动执行以下检查：

1. ✅ 加载并验证配置格式
2. ✅ 验证OKX连接和交易对合法性
3. ✅ 设置单向持仓模式和杠杆
4. ✅ 验证LLM连接
5. ✅ 验证LLM图片解析能力

任何检查失败都会导致程序退出并返回相应错误码。

## 日志

日志同时输出到终端和文件，文件路径格式：`logs/trade_bot_YYYYMMDD_HHMMSS.log`

日志格式：`[YYYY-MM-DD HH:MM:SS] [级别] [模块名] 内容`

## 风险提示

⚠️ **交易有风险，使用需谨慎**

1. 首次运行请务必使用 `demo_mode = true` 在模拟盘测试
2. 确保理解所有配置参数后再切换实盘
3. 建议先在低杠杆、小仓位下测试
4. 程序不保证盈利，请自行承担交易风险

## 许可证

MIT License
