# 视频生成与评测

当前数据为 Core v3.1，默认协议为 `worldline-llm-judge-v5.1`，报告 Valid、Count、Position、SR。评分定义见[评测协议](REFERENCE_EVALUATION.md)。

## 环境

Python 3.9+、FFmpeg 和 ffprobe。在 `benchmark/.env` 中设置 `OPENROUTER_API_KEY`。视频生成默认使用 `bytedance/seedance-2.0-fast`，裁判默认使用 `openai/gpt-5.6-sol`，可分别通过 `--model` 与 `--judge` 指定。

总时长按实际镜头数 × 3 秒预算，默认分辨率为 480p；提交前检查模型是否支持参数。该预算不保证实际切镜间隔，评测使用检测和对齐后的镜头边界。生成参数不进入公开 prompt。

## 运行

以下命令均在 `benchmark/` 内执行。先离线规划完整数据集：

```bash
python3 run_evaluation.py --phase plan --all-cases \
  --protocol worldline-llm-judge-v5.1 \
  --dataset outputs/v3.1 --output evaluations/core-v5.1
```

小批次可将 `--all-cases` 替换为一个或多个 `--case-id CASE_ID`。样本集合、协议、模型与生成参数在批次目录中固定；改变配置时使用新目录。

确认配置后，执行视频生成与评测：

```bash
python3 run_evaluation.py --phase all --all-cases \
  --protocol worldline-llm-judge-v5.1 \
  --dataset outputs/v3.1 --output evaluations/core-v5.1
```

`all`、`generate` 和 `evaluate` 会调用相应付费服务。也可分别运行 `generate` 与 `evaluate`；评测阶段不会重新提交视频生成任务。`media` 只处理本地视频，`report` 只重新生成报告。

检查完成情况：

```bash
python3 validate_evaluation.py --output evaluations/core-v5.1
```

## 结果与人工校准

输出目录保存原始输入、视频、截图、观察结果、目标状态、逐例评分和汇总报告。技术失败或尚未完成的样本单独记录，不当作已完成评测。

准备与导入独立人工标注：

```bash
python3 calibrate_reference.py --phase prepare \
  --source-run evaluations/core-v5.1 --output calibration/core-v5.1
python3 calibrate_reference.py --phase import \
  --output calibration/core-v5.1 --human-file /path/to/item-001.human.json
python3 calibrate_reference.py --phase compare --output calibration/core-v5.1
```

人工标签必须与同批次证据和协议匹配。未导入真实标注时不计算一致性通过率，程序检查不能代替裁判准确性校准。
