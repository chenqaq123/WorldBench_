# Evaluation guide

WorldLine scores the final two observation frames against the observed opening state and the requested event. See the [scoring protocol](REFERENCE_EVALUATION.md) for Valid, Count, Position, and SR.

## Setup

Use Python 3.9+, FFmpeg, and ffprobe. Set `OPENROUTER_API_KEY` in `benchmark/.env`. All commands below run from `benchmark/`.

The implementation defaults to `bytedance/seedance-2.0-fast` for video generation and `openai/gpt-5.6-sol` for judging. Override them with `--model` and `--judge`. Generation budgets three seconds per requested shot at 480p and checks model support before submission. Evaluation uses detected shot boundaries rather than assuming equal shot lengths.

## Run

Plan the full dataset without making API calls:

```bash
python3 run_evaluation.py --phase plan --all-cases \
  --protocol worldline-llm-judge-v5.1 \
  --dataset outputs/v3.1 --output evaluations/core
```

Replace `--all-cases` with one or more `--case-id CASE_ID` arguments to evaluate a subset. Use a separate output directory when changing the sample selection, protocol, or model settings.

Generate videos and evaluate them using the same configuration:

```bash
python3 run_evaluation.py --phase all --all-cases \
  --protocol worldline-llm-judge-v5.1 \
  --dataset outputs/v3.1 --output evaluations/core
```

`all`, `generate`, and `evaluate` make paid API calls. Generation and evaluation can also run as separate phases. The `media` and `report` phases process local artifacts only.

Check the completed batch:

```bash
python3 validate_evaluation.py --output evaluations/core
```

The output directory contains inputs, videos, sampled frames, observations, derived targets, per-sample scores, and summary reports. Pending samples and technical errors are reported separately from evaluated outcomes.

## Human calibration

Create a labeling packet from an evaluation batch, import completed labels, and compare observations:

```bash
python3 calibrate_reference.py --phase prepare \
  --source-run evaluations/core --output calibration/core
python3 calibrate_reference.py --phase import \
  --output calibration/core --human-file /path/to/item-001.human.json
python3 calibrate_reference.py --phase compare --output calibration/core
```

Labels must match the packet's evidence and protocol. Agreement is calculated only after completed human labels are imported.
