# Scoring protocol

Protocol: `worldline-llm-judge-v5.1`. Dataset: Core v3.1.

WorldLine derives the target state by applying the requested event to the observed opening state, then evaluates people and positions in the final wide shot.

## Evidence

A single judge receives:

- Two opening frames sampled at 25% and 75% of the opening shot.
- The requested intermediate content and deterministic event specification.
- Two final frames sampled at 25% and 75% of the final shot.
- Opening requirements, character descriptions, and the final viewpoint instruction.

Entry samples also provide two frames from the entry shot for identity reference. These frames are not scoring points or proof that the requested event succeeded.

Shot intervals come from cut detection. When detected segments do not match the requested sequence, the same judge may perform image-based alignment. The opening, final, and required entry intervals must be reliable; uncertainty in an unused intermediate boundary does not invalidate a sample. Evaluation does not assess every intermediate action.

## Target state

The opening must establish the required characters with reliable identities and physical positions. Entry samples must establish a unique empty place. Missing or additional opening participants, unstable opening states, or uncertain identities can prevent a usable reference.

The judge labels opening positions `P1`, `P2`, and so on, ordered left to right in the first opening frame, with nearer positions first for ties. Labels remain attached to physical positions when the camera changes. The generated layout need not exactly reproduce the prompt's prescribed arrangement.

The target follows the requested event: entry fills the empty place, exit removes the specified character, a swap exchanges two characters' positions, and a static task preserves the state. Failure to perform an event does not change the target. Final frames are not inputs to the target derivation code.

## Participant scope

Count the target interaction group consistently in opening, entry-reference, and final frames.

- Include everyone seated at, occupying, participating in, or directly serving the target table, island, or seating group. This includes additional, standing, duplicated, and unidentified participants.
- Exclude unrelated customers, passersby, and staff working elsewhere. Proximity, matching clothing, or presence in the same room is insufficient for membership.
- Do not replace a missing character with a similar background person, or exclude a visible character because the requested event should have removed them.

Identify the group from the scene before counting; do not narrow its boundary to match the expected total. If membership is uncertain enough to affect the full count, record `count=null` and explain the uncertainty.

## Observability and position

Valid means that the evidence is sufficient to decide whether count and position are correct. Exact camera compliance is not required. Cropping, occlusion, or blur invalidates a sample only when it prevents a decision. A visible lower bound on people is insufficient to establish a complete count.

Position observations distinguish:

| Value | Meaning |
| --- | --- |
| Character ID | A person matched to an established identity |
| `unknown` | A visible person whose identity cannot be matched; a position error |
| `null` | A visible empty position |
| `unobservable` | A position that cannot be reliably observed or matched |

`unobservable` does not automatically make a sample invalid: another confirmed position error or clear layout change can establish failure. Position is undecidable only when neither correctness nor an error can be established.

`layout_changed` records whether the physical position structure differs from the opening. Perspective changes and requested character movements are not layout changes. A positive judgment requires visual evidence.

## Metrics

Both final frames must satisfy each applicable condition; scores do not average frames or select the better one.

| Metric | Passing condition | Denominator |
| --- | --- | --- |
| Valid | Usable opening reference; count and position correctness are decidable in both final frames | All samples |
| Count | Correct participant count in both final frames | Valid samples |
| Position | Correct physical layout and all position occupants in both final frames | Valid samples |
| SR | Valid, Count, and Position all pass | All samples |

Invalid samples receive N/A for Count and Position and fail SR. Conditional accuracy is N/A when no sample is valid. Incomplete runs report pending/error states and provisional summaries rather than treating execution failures as evaluated model outcomes.

## Prompt contract

The opening describes the scene, identities, and initial positions. Intermediate updates identify the entering, exiting, or swapping characters. The final viewpoint specifies a reverse or overhead wide shot without revealing the target count, occupants, or required landmark coverage. Public prompts contain one line per shot and omit duration settings.

Internal layouts and annotations support construction checks. Final position targets come from the observed opening and requested event, not from prescribed seat coordinates.

## Calibration

Although target derivation excludes final frames, the joint judge call may allow final evidence to influence opening observations. Counting, identity matching, and position correspondence require human calibration. See the [evaluation guide](EVALUATION.md) for execution and labeling commands.
