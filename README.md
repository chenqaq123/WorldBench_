# WorldLine Benchmark

WorldLine evaluates whether video models preserve people and spatial relationships across viewpoint changes, person entry, person exit, and seat swaps.

The dataset contains **112 prompts** across 7 scenes, with 3 or 4 people, 3 or 4 shots, and reverse or overhead final views.

[Browse prompts](benchmark/outputs/v3.1/prompts.md) · [Download JSON](benchmark/outputs/v3.1/public_prompts.json)

## Quick start

Requires Python 3.9+. Video evaluation also requires FFmpeg and ffprobe.

```bash
git clone https://github.com/chenqaq123/WorldBench_.git
cd WorldBench_/benchmark
python3 validate_matrix.py
```

Read `cases` in `benchmark/outputs/v3.1/public_prompts.json` to load the dataset, or use each sample's `prompt.txt` as the video model input. Dataset validation runs offline without API credentials.

See the [dataset guide](benchmark/README.md) for file formats and prompt construction, and the [evaluation guide](benchmark/EVALUATION.md) for running the benchmark.
