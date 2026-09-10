# Source catalog

The [catalog](catalog.json) contains 14 excerpts from six works available through Project Gutenberg. Each entry records the author, title, source URL, passage locator, excerpt, and SHA-256 hash.

| Scene | Excerpt IDs |
| --- | --- |
| Café | `alice_riddle`, `alice_seats` |
| Meeting room | `boat_holiday`, `holmes_arrival` |
| Living room | `pride_evening`, `earnest_visit` |
| Dining room | `women_breakfast`, `earnest_tea` |
| Seminar room | `pride_skills`, `holmes_account` |
| Game room | `women_club`, `alice_rules` |
| Kitchen | `boat_stew`, `women_housekeeping` |

Each excerpt supplies eight samples. Within each scene and task, two samples use each of the scene's two excerpts.

Construction adapts the source interaction to controlled characters, layouts, and events. Character attributes and benchmark events are experimental choices rather than claims about the original works. Public prompts paraphrase the interaction without copying dialogue or original character names.

`collect_sources.py` downloads the source text, normalizes whitespace, locates `start_text`, and extracts 300 consecutive words. Excerpts may end mid-sentence; the word order is preserved.
