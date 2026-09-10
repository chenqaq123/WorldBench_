# WorldLine Benchmark

WorldLine 评测视频模型在视角切换与人物进入、离开、换位后，对人数和空间关系的保持能力。

当前 Core v3.1 包含 **112 条多镜头 prompt**：7 个场景、4 类任务、3 / 4 人物、反打 / 俯拍，三镜头与四镜头各 56 条。数据仍为候选集，人工复核与裁判校准尚待完成。

- [Prompt 总览](benchmark/outputs/v3.1/prompts.md) · [JSON 数据](benchmark/outputs/v3.1/public_prompts.json) · [样本清单](benchmark/outputs/v3.1/core_matrix.manifest.json)
- [构造与数据说明](benchmark/README.md)
- [评测协议](benchmark/REFERENCE_EVALUATION.md) · [评测运行方法](benchmark/EVALUATION.md)
- [论文仓库](https://github.com/chenqaq123/WorldBench)

## 快速使用

Python 3.9+，仅使用标准库；视频处理另需 FFmpeg / ffprobe。

```bash
git clone https://github.com/chenqaq123/WorldBench_.git
cd WorldBench_/benchmark
python3 -m unittest discover -s tests -q
python3 validate_matrix.py
```

以上检查完全离线，无需 API key。直接使用数据时，读取 `outputs/v3.1/public_prompts.json` 的 `cases`，或逐例读取 `prompt.txt`。

需要重新构造 prompt 或生成、评测视频时，在 `benchmark/.env` 中配置自己的 API key，具体命令见上述文档。
