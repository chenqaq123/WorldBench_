# Dataset guide

The dataset is stored in `outputs/v3.1/`. Use the [manifest](outputs/v3.1/core_matrix.manifest.json) to select samples, the [JSON collection](outputs/v3.1/public_prompts.json) to load them, or the [prompt index](outputs/v3.1/prompts.md) to browse them.

| Dimension | Coverage |
| --- | --- |
| Tasks | Static viewpoint change, person entry, person exit, position swap |
| Scenes | Café, meeting room, living room, dining room, seminar room, game room, kitchen |
| People | 3 or 4 |
| Final view | Reverse or overhead |
| Shots | 3 or 4; 56 samples each |

The 112 prompts use 14 [source excerpts](sources/README.md), with controlled assignments of stories, character attributes, and layouts. The opening establishes the scene; intermediate shots provide partial views and specified events; the final shot changes the viewpoint. Human review and judge calibration remain pending.

## Files

Each sample contains:

| File | Purpose |
| --- | --- |
| `prompt.txt` | Complete video model input, one line per shot |
| `prompt.public.json` | Per-shot `content` and `viewpoint` fields |
| `episode.internal.json` | Characters, events, and designed states |
| `annotations.hidden.json` | Design constraints and evaluation references |
| `run.json` | Source, configuration, and construction outputs used by validation |

The JSON collection stores sample metadata and shots under `cases`. Submit the public prompt to the video model. Evaluation derives target positions from the observed opening and the requested event, as defined in the [scoring protocol](REFERENCE_EVALUATION.md).

## Construct prompts

Run commands from `benchmark/`. Copy `.env.example` to `.env`, add your API key, and select VAPI or OpenRouter with `PROMPT_PROVIDER`. Configure the generation and audit models using the corresponding provider variables in the template.

Plan a separate dataset directory, then generate its prompts:

```bash
python3 generate_core_v3.py --output-root outputs/custom
python3 generate_core_v3.py --output-root outputs/custom --execute --resume --workers 4
```

Planning is offline. `--execute` makes paid API calls; `--resume` reuses completed stages when their request configuration matches.

## Validate and export

```bash
python3 validate_matrix.py
python3 -m unittest discover -s tests -q
```

Both commands run offline. For a custom collection, supply `--manifest outputs/custom/core_matrix.manifest.json --outputs outputs/custom` to the validator. Export it with `python3 export_prompts.py --output-root outputs/custom`; add `--overwrite` to replace existing exports.
