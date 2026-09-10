# Prompt 构造与数据

当前数据目录为 `outputs/v3.1/`，共 112 条。使用 [manifest](outputs/v3.1/core_matrix.manifest.json) 选择样本；可直接查看 [prompt 总览](outputs/v3.1/prompts.md) 或读取 [公开 JSON](outputs/v3.1/public_prompts.json)。

## 数据设计

|维度|配置|
|---|---|
|任务|Static Viewpoint Change、Person Entry、Person Exit、Position Swap|
|场景|Café、Meeting room、Living room、Dining room、Seminar room、Game room、Kitchen|
|人物|3 / 4 人|
|最终视角|Reverse Axis / Overhead|
|镜头数|3 / 4 镜头，各 56 条|

素材取自 6 部作品的 14 段核验原文，每段用于 8 条样本，详见[素材库](sources/README.md)。人物性别、衣服颜色、素材和布局按确定性方案分配。

开场建立人物与位置；中间镜头形成局部观察，并执行指定事件；最终全景改变观察视角。最终 Viewpoint 不透露人数、座位或位置答案。当前[评测协议](REFERENCE_EVALUATION.md)根据实际开场与指定事件推导目标。

## 数据文件

每条样本包含：

|文件|用途|
|---|---|
|`prompt.txt`|视频模型的完整输入，一行一个镜头|
|`prompt.public.json`|各镜头的 `content` 和 `viewpoint`|
|`episode.internal.json`|人物、事件与内部状态|
|`annotations.hidden.json`|设计约束和评测参照信息|
|`run.json`|校验及构造复用所需的来源、配置与阶段结果|

公开 JSON 的 `cases` 提供样本 ID、任务、场景、人数、最终视角与逐镜头文本。送入视频模型时使用公开 prompt；内部状态与标注用于验证和评分。

## 构造流程

五个独立 LLM 阶段依次执行素材抽象、人物配置、故事规划、Content 渲染和审校。Python 确定布局、状态变化和相机计划，并检查格式、实验控制、来源和文字一致性。

以下命令均在 `benchmark/` 目录执行。Python 3.9+ 即可，无需第三方 Python 包。

将 `.env.example` 复制为 `.env` 并填入自己的 key；已有配置时直接编辑。通过 `PROMPT_PROVIDER` 选择 VAPI 或 OpenRouter，模型由相应的 `*_PROMPT_MODEL` 与 `*_AUDIT_MODEL` 设置；可选阶段覆盖见模板。各阶段独立调用，服务间不自动回退。

只规划新的数据目录，不调用模型：

```bash
python3 generate_core_v3.py --version 3.1 --output-root outputs/my-v3.1
```

实际构造与断点继续：

```bash
python3 generate_core_v3.py --version 3.1 --output-root outputs/my-v3.1 \
  --execute --resume --workers 4
```

`--execute` 会产生 API 费用。`--resume` 仅复用请求配置完全一致的已成功阶段；新批次应使用独立目录。

## 校验与导出

校验仓库自带的完整数据集：

```bash
python3 validate_matrix.py
python3 -m unittest discover -s tests -q
```

校验新批次并导出：

```bash
python3 validate_matrix.py \
  --manifest outputs/my-v3.1/core_matrix.manifest.json --outputs outputs/my-v3.1
python3 export_prompts.py --output-root outputs/my-v3.1
```

导出前会校验完整集合；已有导出需要显式添加 `--overwrite`。文本校验通过不代替人工复核或视频实验。
