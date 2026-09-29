# ProofWeave

[![CI](https://github.com/Duckweed-yhb/ProofWeave/actions/workflows/ci.yml/badge.svg)](https://github.com/Duckweed-yhb/ProofWeave/actions/workflows/ci.yml)

[English](./README.en.md) · **中文**

**可复现的 NVIDIA 供应链与合作关系图谱 —— 每条关系都有评分、有出处、可追溯。**

本仓库是 ARTi 研发岗位挑战的交付物。题目要求：
> *在 NVIDIA 与宇树科技中任选其一，基于合法可访问的公开资料，构建一个可复现的供应链与合作关系研究服务。目标不是生成一段摘要，而是将关系结论、证据、时效、方向和可解释评分连接起来，让 reviewer 可以理解、运行和追溯你的判断。*

---

## 1. 研究对象与快照

| | |
|---|---|
| **研究主体** | NVIDIA Corporation（英伟达） |
| **证券标识** | NVDA · 纳斯达克 |
| **快照日期** | **2026-09-29** |
| **主要参考文件** | NVIDIA FY2026 Form 10-K（2026-02-25 提交，截至 2026-01 财年）、NVIDIA Q2 FY2027 10-Q（截至 2026-07-26） |
| **覆盖范围** | 23 家公司节点（21 家上市 + 2 家未上市 + 1 个"匿名客户"合成节点），共 25 条关系，覆盖 `supplier / customer / partner / investor_or_investee / peer` 五类 |
| **不覆盖** | 分地区收入、产品路线图押注、非公开合同条款、任何目标价。 |

> **免责声明**：本快照仅用于研究复现，**不构成投资建议**。

### 关系图谱一览

```mermaid
graph LR
  NVDA((NVIDIA))

  subgraph 供应商
    TSMC[台积电 TSMC]
    SKH[SK 海力士]
    MU[美光 Micron]
    SS[三星 Samsung]
    AMKR[Amkor]
    FXA[鸿海/富士康]
    WST[纬创]
    FN[Fabrinet]
  end

  subgraph 客户
    MSFT[微软]
    GOOG[谷歌]
    ORCL[甲骨文]
    CRWV[CoreWeave]
    META[Meta]
    AMZN[亚马逊 AWS]
  end

  subgraph 被投企业
    OAI[OpenAI]
    ANTH[Anthropic]
    MRVL[Marvell]
    LITE[Lumentum]
    COHR[Coherent]
  end

  subgraph 同业
    AMD[AMD]
    INTC[英特尔]
    AVGO[博通]
  end

  TSMC -->|晶圆代工| NVDA
  SKH -->|HBM 显存| NVDA
  MU -->|HBM 显存| NVDA
  SS -->|存储/代工| NVDA
  AMKR -->|先进封装| NVDA
  FXA -->|整机组装| NVDA
  WST -->|整机组装| NVDA
  FN -->|整机组装| NVDA

  NVDA -->|GPU| MSFT
  NVDA -->|GPU| GOOG
  NVDA -->|GPU| ORCL
  NVDA -->|GPU| CRWV
  NVDA -->|GPU| META
  NVDA -.->|GPU, 推断| AMZN

  NVDA -->|股权投资| OAI
  NVDA -->|股权投资| ANTH
  NVDA -->|股权投资| MRVL
  NVDA -->|股权投资| LITE
  NVDA -->|股权投资| COHR

  AMD <-.->|同业| NVDA
  INTC <-.->|同业| NVDA
  AVGO <-.->|同业| NVDA
```

实线 = `confirmed`（已确认）；虚线 = `inferred`（推断）/ `peer`（同业）。带评分的完整边列表见 `/graph` 接口。

## 2. 快速开始

需要 Python ≥ 3.11。

```bash
# 1. 创建虚拟环境
python -m venv .venv
# Windows:
.\.venv\Scripts\Activate.ps1
# macOS/Linux:
# source .venv/bin/activate

# 2. 安装（可编辑模式）+ 开发依赖
pip install -e ".[dev]"

# 3. 跑测试（应输出 23 passed）
pytest -q

# 4. 启动 HTTP API
uvicorn proofweave.api:app --reload --port 8123
#   然后浏览器打开 http://127.0.0.1:8123/docs 看交互式 Swagger
```

无需任何密钥或 `.env`。只有当你后续扩展爬虫时才需要参考 `.env.example`。

## 3. 命令行

```bash
proofweave summary                                   # 一行一条关系的速览
proofweave list --type supplier --min-score 80        # JSON 筛选输出
proofweave show nvda-tsmc-foundry                    # 单条关系含完整证据
proofweave graph --out graph.json                    # 导出节点/边图
```

## 4. HTTP JSON API

所有接口都从磁盘快照读取，**请求时不发起任何网络调用**。

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/health` | 快照日期、关系/公司数量。 |
| GET | `/stats` | 一键聚合：按关系类型/状态计数、分数桶分布。 |
| GET | `/companies` | 全部公司节点（含美国上市公司 SEC CIK 编号）。 |
| GET | `/relationships` | 筛选 + 分页。参数：`relation_type`、`status`、`direction`、`min_score`、`object_company`、`limit`（1-200）、`offset`。 |
| GET | `/relationships/{id}` | 单条关系含完整证据列表。不存在返回 404。 |
| GET | `/graph` | 导出节点 + 边，供可视化。 |

示例：

```bash
curl "http://127.0.0.1:8123/relationships?relation_type=supplier&min_score=90"
curl "http://127.0.0.1:8123/relationships/nvda-amkor-packaging"
curl "http://127.0.0.1:8123/relationships?status=unknown"     # 那条故意标 unknown 的边界行
```

非法枚举值或越界分页返回 **422**；不存在的 ID 返回 **404**。

## 5. 数据模型

```
Company   { id, name, ticker, exchange, cik?, is_listed }
Evidence  { url, publisher, published_at, accessed_at, locator, access_note, quote? }
Relationship {
    id, subject, object_company,
    relation_type  ∈ supplier | customer | partner | investor_or_investee | peer,
    direction      ∈ inbound  (对方 → NVIDIA) | outbound (NVIDIA → 对方) | both,
    status         ∈ confirmed | inferred | unknown,
    as_of, rationale, evidence[], quantitative_note?, uncertainty_note?, score
}
```

每个字段的含义都在 `proofweave/models.py` 里有 docstring。

## 6. 评分公式（0–100，全加法）

分数在**加载时由证据列表现算**，从不手写进 JSON：

```
base              已确认 70 / 推断 40 / 未知 15
+ evidence_count   每条证据 +3，上限 5 条
+ independence    每个不同 publisher +4，上限 5 家
+ recency          最新证据 ≤180 天 +10，≤365 天 +6，≤730 天 +3
+ quantitative     有公开数字锚点 +8（例如"约占台积电 19% 收入"）
− penalty          推断但只有 1 家来源 −10；unknown −20
= clamp(0, 100)
```

每一项（`base / evidence_count_bonus / independence_bonus / recency_bonus / quantitative_bonus / penalty / total / rationale`）都随关系返回，reviewer 可以手算复核每一分。见 `proofweave/scoring.py`。

## 7. 数据来源与合规

所有数据来自**公开、免登录、无付费墙**的来源：

- **SEC EDGAR** NVIDIA 文件（CIK 0001045810）—— FY2026 10-K、Q2 FY2027 10-Q。
- **NVIDIA 官方新闻稿 / 博客**（`nvidianews.nvidia.com`、`blogs.nvidia.com`）。
- **对方公司官方页面**——`amkor.com`、`cloud.google.com/blog`。
- **主流财经媒体**——Nasdaq、Korea Herald、Counterpoint、CTOL。

我们**不**绕过 robots、登录、付费墙、验证码或限流。仓库里不包含任何密钥、个人数据或客户机密。快照 JSON 直接入库，reviewer **无需**重新抓取任何东西即可复现。

### 故意保留的边界案例

10-K R14 披露**三大直接客户分别占收入的 30%、18% 和约 1x%**，但**没有点名**。我们把它作为一行 `status=unknown`、分数约 20 入库，并明确**拒绝猜测**"30% 那个客户是微软"。乱猜正是题目警告的"新闻共现误判"。

## 8. AI 使用声明（对应挑战第 10 条）

- **AI 辅助用于**：起草样板结构、建议 Pydantic 字段名、通过搜索定位公开 URL、解释报错信息。
- **本人（余泓彬）负责**：选择 NVIDIA 作为研究对象、筛选每一条关系、把每条归类为 `confirmed / inferred / unknown`、挑选证据 URL 与原文引文、设计评分公式、撰写本 README。
- **未向任何 AI 工具输入**：API 密钥、个人数据、客户机密或任何非公开资料。
- 快照里的每一个 URL 在提交前都人工打开核对过。

## 9. 已知局限与未来工作

- **HBM 各家份额**（SK 海力士约 50-60%、三星约 25-30%、美光剩余）是*分析师估计*，不是 NVIDIA 披露——已在该行明确标注。
- **AWS / 亚马逊**标为 `inferred`，因为 NVIDIA 任何一份一手文件都没点名；要升级需要找到一手来源。
- **同业分类**用的是行业共识，没有正式拉 GICS；为了不引入付费依赖，没有调用第三方 GICS API。
- **尚未接入实时爬虫**。要刷新数据时，编辑 `proofweave/data/snapshot_<date>.json`，重跑 `pytest`，并更新 `loader.py` 里的 `_DEFAULT_SNAPSHOT`。
- 尚未覆盖的边界：任意 `as_of` 时间旅行查询、多跳图遍历、跨交易所同名公司合并。

## 10. 目录结构

```
proofweave/
├── models.py            # Pydantic 数据模型
├── scoring.py           # 0-100 加法评分引擎
├── api.py               # FastAPI JSON API
├── cli.py               # typer 命令行
└── data/
    ├── loader.py
    └── snapshot_2026_09_29.json   # 冻结、可审计的交付物
tests/                    # 23 个测试，含 404 / 422 / 分页 / unknown 边界
```

## 11. 许可证

MIT。
