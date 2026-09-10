# WorldLine Python Evaluation Suite

> 仓库范围：代码、prompt 数据和文本构造记录已收录；历史视频评测与人工标注包保留在原本地工作区，文中相应路径不随仓库上传。

**当前默认协议为 v5.1，详见 [初始场景 + 指定 Update + 最终全景](REFERENCE_EVALUATION.md)。** 它使用实际初始位置推导更新目标，不再采用预填的最终地标座位表；Valid 只判断证据是否足够，不要求精确摄影或预设座位布局。v5.1 明确开场和最终帧都忽略无关背景人物，同桌额外人物仍计数，不改变初始角色门槛或评分公式。默认数据目录为 outputs/v3.1，输出目录为 evaluations/seedance-2.0-fast-evidence-v5.1。保留四项主指标，单次 Sol 主观察，无复核；旧标注与报告不改动。已完成的 16 条 v5 重评（本地历史产物，未随仓库上传；`evaluations/acceptance-v3.1-16-seedance-fast-v5/REEVALUATION.md`） 为 Valid 62.5%，该批评测费用约 $0.46；此次 v5.1 修改没有新的付费调用或实验分数。

以下为旧 v2/v3 评测的历史执行与复现记录；其中“当前/默认”指该历史版本，不覆盖上面的新协议。重放旧两帧协议时必须显式指定 --protocol worldline-llm-judge-v3、旧 dataset 和独立 output；五帧结果只按原协议读取。

v3 数据定稿及独立的两帧人工校准入口见 [V3.md](V3.md)。现已本地准备十条旧视频的盲标包，人工与付费裁判标注尚未执行；它们是开发校准材料，不是 v3 新视频结果。未来全量选择使用 --all-cases，必须显式指定目标 dataset 和新的 output；不会将 pending 样本提交给生成服务，也不会将旧子集批次静默当作全量批次续跑。

视频生成和评测位于独立 Python 框架内，不依赖网页测试环境。入口为 `run_evaluation.py`，使用 `benchmark/.env` 的 OpenRouter 配置。当前全流程仅使用 **`openai/gpt-5.6-sol` 单裁判**，不进行第二模型复核、仲裁或自动发起人工复核。发送给裁判的是视频抽帧，视频生成和裁判均产生 API 费用。

## 时长与批次

总时长统一按 **实际镜头数 × 3 秒** 计算：3 shots → 9 秒，4 shots → 12 秒，5 shots → 15 秒。每条 case 的镜头数和总时长都冻结在 manifest 中。总时长只进入视频 API 的 `duration`，不会修改公开 prompt，也不会添加时间戳或每镜时长。

这是生成时长预算，不保证联合生成的视频严格每 3 秒切镜。评测必须从实际视频识别镜头边界，不能直接将 `[0,3]、[3,6]、[6,9]` 当成真实分镜。模型不支持某个 case 的总时长时，整批在提交前报错，不自动截短或拆成多个视频。

当前十条清单均为 3-shot，因此每条请求 **9 秒、480p、16:9**。分辨率统一选择当前模型支持的最低档；已查询 Seedance 2.0 Fast 支持 480p / 720p，因此采用 480p。实际提交前再次检查模型能力；更换模型时需按其最低受支持分辨率配置，不默认沿用更高分辨率。

清单覆盖 7 个场景、四类任务、5 个反打与 5 个俯拍、5 个三人与 5 个四人布局。当前两帧协议默认输出为 `evaluations/seedance-2.0-fast-pilot-10-3s-per-shot-480p-sol-2frames/`，不覆盖旧结果。已完成的 Sol 五帧实验位于 `evaluations/seedance-2.0-fast-pilot-10-3s-per-shot-480p-sol-single/`；9 秒 / 480p 原始生成和第一轮评测位于 `evaluations/seedance-2.0-fast-pilot-10-3s-per-shot-480p/`；校准后的 Gemini 五帧双裁判报告位于 `evaluations/seedance-2.0-fast-pilot-10-3s-per-shot-480p-eval-v2/`。此前 15 秒 / 720p 批次仍在 `evaluations/seedance-2.0-fast-pilot-10/`，不混合计分。中间的 `seedance-2.0-fast-pilot-10-3s-per-shot/` 是未执行的 9 秒 / 720p 计划。

## 流程

1. 冻结样本清单、公开 prompt、隐藏标注、文件哈希和生成参数。每条只生成一次，不根据结果好坏替换样本。
2. 提交 Seedance 2.0 Fast；立即保存任务 ID；查询完成后保存原视频、实际元数据及费用。
3. 用 FFmpeg 固定 scene-difference 阈值 0.30 提取物理硬切边界。物理片段数量与请求镜头数一致时按时间顺序对应，不将这种对应当成视角合规证明；数量不一致时，Sol 结合带时间戳的 2 fps 图片序列、候选边界及每个物理片段的中点图匹配镜头，切镜起点必须采用检测时间。缺镜、多切镜和连续运镜分别记录。该检测阈值只在本次 pilot 验证，不能宣称对所有视频都可靠。
4. 在最终全景实际起止区间的 **25% 和 75%** 位置固定抽取 **两帧**，即 `start + 0.25 × (end-start)` 和 `start + 0.75 × (end-start)`。这是最终全景内的两个时点，不是整条视频的 25% / 75%。不能挑选更有利的帧替代失败读数。身份参照和独立事件诊断的抽帧不属于这两个评分点。
5. 仅一次 Sol 盲评读取固定帧和身份参照，记录视角合规、可观察性、实际人数和各地标座位占用，不接收 task、事件、最终期望人数或目标座位表。不调用第二裁判，不仲裁，也不把已有 Gemini 或人工判断送入 Sol。一次有效返回即采用；网络/格式错误仍按有界错误重试处理，不是结果复核。
6. Python 对照隐藏标注评分。两帧均符合观察条件才有效，人数分和位置分分别要求两帧全对；未知身份算位置错误，无法观察座位算观察无效，空座与不可见座位严格区分。所有任务都评分全部人物和座位。开场与 partial 不计入两个主分。
7. 仍由 Sol 在另一次独立请求中检查开场建立、partial 离屏、事件执行和分镜序列，作为轨迹诊断，不替代或改变有效最终全景的端点评分。这次请求可以读取故事要求，但与盲评没有共享对话，也不回写盲评答案。输入为 2 fps 加每个物理片段中点图片，不能声称读过连续视频或判断未采样时刻；采样不足时保留不确定性。保存 JSON、CSV、可播放视频的 HTML 和 Markdown 汇总。

因此，标准 case 通常是两次 Sol 访问：一次最终全景盲评，一次独立事件诊断。只有物理片段数不匹配时增加一次镜头对齐访问，不是第二裁判复核。报告不再输出双裁判一致率或待复核清单；不确定性作为结果字段保留，不触发更多调用。两帧协议记为 `worldline-llm-judge-v3`；历史五帧仍为 v2，读取旧报告、校验和单案例模型对照时保留其原始采样契约，不从旧五帧中随意删三帧来构造新分数。

### Valid 是什么

`Valid` 表示 **可评测**，不是人数或位置正确。每张评分帧都必须同时满足：实际视角、尺度和指定座位区域覆盖符合要求（View Compliance）；人数与各座位占用状态能被可靠观察（Readable）。两张评分帧都满足时，case 的 Valid 才为 true。可见但身份不确定记为 unknown，算位置错误；空座记为 null，仍可观察；遮挡或无法定位的座位记为 unobservable，导致无效。

例如人数看得清但多出一人：Valid 可以为 true，人数分为 false。若一个关键座位看不清：Valid 为 false，当前代码会把人数和位置两项主分都标为 N/A，联合成功为 false。本次只减少评分帧数量，没有改变这个共用门控。

主报告按 task 同时报告视角合规率、有效观察率、人数条件准确率、位置条件准确率和全样本端到端成功率，并提供 task 等权结果及有效分母。缺失视频与无效观察不从端到端分母删除。未执行的裁判步骤不冒充模型失败，临时报告明确标记未完成。未经人工校准，LLM 结果只能作为 pilot 自动评测，不视为已验证的正式 benchmark 分数。

## 执行

在 `benchmark/` 下运行，默认只规划，不访问付费接口：

```bash
python3 run_evaluation.py --phase plan
python3 run_evaluation.py --phase generate
python3 run_evaluation.py --phase evaluate
python3 run_evaluation.py --phase report
python3 validate_evaluation.py
python3 -m unittest discover -s tests -q
```

本次复用已有十条视频的单裁判重评命令（付费上传抽帧，不重新生成视频）：

```bash
python3 run_evaluation.py --phase evaluate \
  --reuse-videos-from evaluations/seedance-2.0-fast-pilot-10-3s-per-shot-480p-eval-v2 \
  --workers 2
```

`--judge` 默认为 `openai/gpt-5.6-sol`；`--second-judge` 已移除。原生视频输入已从评测阶段移除，Sol 的温度参数省略，推理设置使用服务默认值。执行前读取并保存模型能力快照，校验图片与结构化输出支持；不将不兼容请求静默转给 Gemini。

`--phase all` 顺序连接生成与裁判；`--phase media` 仅为已有视频生成本地概览图，不上传给裁判、不产生评测分数。媒体处理需要本地 FFmpeg / FFprobe 和 Pillow。现有 prompt 构造器仍只依赖 Python 标准库。

续跑复用冻结记录和已完成阶段。明确的 HTTP 拒绝（如余额不足 402）在问题解决后，可显式使用 `--phase generate --retry-rejected` 重试；超时等不确定提交不会自动重试，防止重复收费。裁判进程最多两个并发访问，`in_flight_budget_exhausted` 按 Retry-After 有界退避后重试，与真正余额不足区分；每次失败和返回均保留。更改时长、模型、裁判或样本清单必须使用新目录。

如果只修订评测而不重生成视频，在新输出目录使用 `--reuse-videos-from <旧批次目录>`。复用前严格检查生成参数及全部输入哈希，不允许不同视频混入。每个 case 保留 `input/`、视频、生成请求与任务、`cuts.json`、`alignment.json`、`frames.json`、`sequence.frames.json`、原始 `judge/` 调用、`observation.json`、`diagnostics.json` 和 `score.json`。新单裁判报告把复用视频费用列为历史费用，本批新增视频费用为零。`validate_evaluation.py` 校验媒体哈希、盲评输入、单一模型/图片输入约束和逐帧评分可复现性，不代替人工视觉校验。

## 当前执行状态

### 当前两帧版本

最终全景默认两帧的代码、裁判提示词、报告和校验已更新；本次没有重新发送素材或发起付费重评。网页上此前完成的十条仍是五帧实验，不能把下面的历史指标当作两帧结果。

### 已完成的 Sol 五帧单裁判 pilot

单裁判代码和默认配置已完成，55 项本地测试通过。十条已有视频均已重评完成，完整性验证 10/10、零错误；21 次成功模型调用包括 10 次盲评、10 次独立事件诊断、1 次镜头对齐，无复核/仲裁调用。另有 2 次并发预算拒绝，按 Retry-After 重试后成功，原错误记录保留。新增裁判费用 $0.7508285，视频新增费用为零。有效最终全景 4/10，条件人数准确率 3/4，条件位置准确率 1/4，端到端成功 1/10。原 Gemini 结果保留作历史对照，详见Sol 报告（本地历史产物，未随仓库上传；`evaluations/seedance-2.0-fast-pilot-10-3s-per-shot-480p-sol-single/report.html`）及迁移结果分析（本地历史产物，未随仓库上传；`evaluations/seedance-2.0-fast-pilot-10-3s-per-shot-480p-sol-single/ANALYSIS.md`）。

厨房退出案例在本次 Sol 全量运行中被判为斜俯拍、座位覆盖不足，主分为 N/A，和此前 Sol 单例结果不同。两次的盲评正文、schema、图片哈希和采样时点相同；未重跑挑选有利答案。该差异说明单裁判仍存在判断波动，本次迁移并未解决可观察性门控问题，也不构成人工准确率验证。

### 固定帧裁判对照

`compare_observer.py` 可对一条已评测 case 更换图像观察裁判，不重生成视频，不修改既有 Gemini 报告。默认只生成本地计划；显式传入 `--run` 才查询模型目录并发送付费请求。它沿用源协议的原始身份参照和最终全景帧（v2 五帧、v3 两帧）、盲评文本、输出 schema 与评分函数；不发送 task、隐藏目标、原裁判答案或人工反馈。源文件与图片哈希冻结在新目录，完整请求、响应、观察记录和对照分数均保留。

```bash
python3 compare_observer.py \
  --source-case evaluations/seedance-2.0-fast-pilot-10-3s-per-shot-480p-eval-v2/WL-CORE-KITCHEN-EXIT-3P-TOP-3S \
  --output evaluations/judge-comparison-gpt-5.6-sol-kitchen-exit-v2 \
  --model openai/gpt-5.6-sol
```

确认向该模型发送图片及付费评测的授权后，追加 `--run` 执行。OpenRouter 当前列出的 Sol 支持图片与结构化输出、不列出 `temperature` 参数；对照入口显式省略该参数并记入请求，保留模型默认推理设置。历史 Gemini 请求记录不变。此入口仅比较最终全景观察，不把未执行的视频轨迹诊断记成 Sol 失败，也不能据单个案例宣称某裁判准确率更高。

厨房退出案例暴露了 v2 的门控耦合：Flash 的原始观察为人数正确、位置错误；Pro 与其仲裁认为座位映射不可观察，使人数和位置主分同时成为 N/A，而不是位置通过。此前单案例对照保留旧规则，结果为五帧均报告可观察、2 人，人数正确、位置错误，与 Flash 的原始结构化观察一致；一次调用，费用 $0.0424835。详见历史单案例对照报告（本地历史产物，未随仓库上传；`evaluations/judge-comparison-gpt-5.6-sol-kitchen-exit-v2/REPORT.md`）。单例一致不代表人工验证；随后按用户要求把全流程默认裁判切换为 Sol。

### 已完成的 Gemini pilot

用户已补充余额并明确授权 Gemini 付费视觉评测。本次 9 秒 / 480p 的 10 条视频均已生成，校准后的 10 条评测均完成，完整性验证为 10/10、零错误，48 项测试通过。服务实际返回统一 864×496、约 9.04 秒，保留原视频而不强制缩放。结果与分析见 报告（本地历史产物，未随仓库上传；`evaluations/seedance-2.0-fast-pilot-10-3s-per-shot-480p-eval-v2/report.html`）和实验分析（本地历史产物，未随仓库上传；`evaluations/seedance-2.0-fast-pilot-10-3s-per-shot-480p-eval-v2/ANALYSIS.md`）。

## 接口依据

视频生成适配器使用 OpenRouter 的[异步视频生成接口](https://openrouter.ai/docs/guides/overview/multimodal/video-generation)。评测迁移依据 [GPT-5.6 Sol 官方模型说明](https://developers.openai.com/api/docs/models/gpt-5.6-sol)：使用图片输入和结构化输出，不发送原生视频。OpenRouter 路由能力在执行前另行核验。实际模型、输入、调用返回、用量及视觉证据均保存在当前批次内。
