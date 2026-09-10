# WorldBench_ · WorldLine Benchmark

本仓库收录 WorldLine Benchmark 的 Python prompt 构造器、视频生成与评测框架、研究设计和可追溯数据。论文源文件位于独立的 [WorldBench 仓库](https://github.com/chenqaq123/WorldBench)。

## 当前数据

**WorldLine Core v3.1：112 条已完成 prompt，三镜头与四镜头各 56 条。** 覆盖 7 个场景、4 类任务、3 / 4 人物及反打 / 俯拍两类最终视角。素材来自 6 部作品的 14 段已核验原文，人物性别、衣服颜色与素材分配经过均衡检查。

- [112 条 prompt 总览](benchmark/outputs/v3.1/prompts.md)
- [公开 JSON](benchmark/outputs/v3.1/public_prompts.json)
- [当前样本清单](benchmark/outputs/v3.1/core_matrix.manifest.json)
- [构造与校验记录](benchmark/outputs/v3.1/CONSTRUCTION.md)
- [9 条指代消歧修订及前后对照](benchmark/outputs/v3.1/revisions/pronoun-20260910/REPORT.md)
- [新增 96 条与原有 16 条的质量比较](benchmark/outputs/v3.1/QUALITY_COMPARISON.md)

2026-09-10 上传前验证：**136 项离线测试通过，112 条当前样本全量校验零错误**。数据仍为候选集，尚待人工复核与裁判校准，未声明为正式冻结版本。修订记录保存原始输出和后续审校，旧版数据按各自版本保留。

## 仓库结构

```text
WorldBench_/
├── benchmark/
│   ├── generate_core_v3.py     当前 v3.1 规划与构造入口
│   ├── run_evaluation.py       视频生成与 LLM 评测入口
│   ├── validate_matrix.py      prompt 集合离线校验
│   ├── export_prompts.py       公开 prompt 导出
│   ├── worldline/              构造、布局、评分与接口实现
│   ├── tests/                  离线测试
│   ├── sources/                原文摘录、出处与哈希
│   ├── outputs/v3.1/           当前 112 条数据与修订档案
│   ├── outputs/v2/             历史 112 条三镜头样本
│   ├── outputs/v3/             旧 3.0 设计计划
│   └── experiments/            文本审阅与构造连接记录
└── docs/proposal.md            研究设计
```

本次提交包含源代码、文档、prompt 数据、中间产物与构造记录。历史视频评测目录 `benchmark/evaluations/`、人工标注包 `benchmark/calibration/`、生成视频、密钥及缓存未上传。相关历史路径在文档中注明；独立网页测试环境和论文文件也不在本仓库内。

## 下载与离线检查

构造器仅使用 Python 3.9+ 标准库，无需安装 Python 第三方包。视频处理和媒体集成测试使用 FFmpeg / ffprobe；缺少它们时媒体测试会跳过。

```bash
git clone https://github.com/chenqaq123/WorldBench_.git
cd WorldBench_/benchmark
python3 -m unittest discover -s tests -q
python3 validate_matrix.py \
  --manifest outputs/v3.1/core_matrix.manifest.json \
  --outputs outputs/v3.1
```

这两项检查无需 API key，不调用付费服务。只使用已有 prompt 时，直接读取 `outputs/v3.1/public_prompts.json` 中的 `cases`，或逐例读取 `prompt.txt`。

当前数据以 v3.1 manifest 为准；不要递归合并 `outputs/` 下的历史版本与修订快照。`annotations.hidden.json` 和 `run.json` 用于内部验证与追溯；提交给视频模型的输入应使用公开 prompt。

## 配置与构造

在 `benchmark/` 内将 `.env.example` 复制为 `.env` 并填入自己的 key；已有 `.env` 时直接编辑。环境文件已加入忽略规则。

`.env.example` 提供 VAPI / OpenRouter 配置模板。2026-09-10 新增 96 条及随后 9 条修订审校使用 VAPI 的 `gemini-3.7-flash`；如需沿用该配置，将 `VAPI_PROMPT_MODEL` 与 `VAPI_AUDIT_MODEL` 均设为 `gemini-3.7-flash`。每条历史产物的实际服务和模型以 `run.json` 为准。

只规划一个独立的新批次：

```bash
python3 generate_core_v3.py --version 3.1 --output-root outputs/my-v3.1
```

需要实际构造时显式添加 `--execute`；调用会产生服务费用。完整的配置、断点继续与导出说明见 [构造器文档](benchmark/README.md)。

## 评测协议与研究设计

当前默认协议是 **worldline-llm-judge-v5.1**：根据实际开场与指定 Update 推导目标，在最终两帧评分，报告 Valid、Count、Position、SR。现有 16 条视频成绩属于旧 v5，不能作为 v5.1 或新增 96 条的结果。

- [当前评测协议](benchmark/REFERENCE_EVALUATION.md)
- [视频生成与评测操作说明](benchmark/EVALUATION.md)
- [素材来源](benchmark/sources/README.md)
- [Benchmark Proposal](docs/proposal.md)

可以先离线规划新的全量评测目录：

```bash
python3 run_evaluation.py --phase plan \
  --protocol worldline-llm-judge-v5.1 --all-cases \
  --dataset outputs/v3.1 --output evaluations/core-evidence-v5.1
```

实际视频生成和 LLM 评测需要相应 API 配置与费用；本仓库上传和离线验证没有发起新的生成或评测请求。
