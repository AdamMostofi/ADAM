# Third-party notices

ADAM is MIT-licensed ([LICENSE](LICENSE)). It uses or includes the following, each under its own license.
Checked 2026-11-20.

## Included in this repository

| What | Where | License | Copyright |
|---|---|---|---|
| Cinzel font | `interface/web/static/fonts/Cinzel.woff2` | SIL Open Font License 1.1 ([OFL-Cinzel.txt](interface/web/static/fonts/OFL-Cinzel.txt)) | 2020 The Cinzel Project Authors |
| Oswald font | `interface/web/static/fonts/Oswald.woff2` | SIL Open Font License 1.1 ([OFL-Oswald.txt](interface/web/static/fonts/OFL-Oswald.txt)) | 2016 The Oswald Project Authors |
| IBM Plex Mono font | `interface/web/static/fonts/IBMPlexMono-*.woff2` | SIL Open Font License 1.1 ([OFL-IBMPlexMono.txt](interface/web/static/fonts/OFL-IBMPlexMono.txt)) | 2017 IBM Corp., Reserved Font Name "Plex" |
| AI Elements components (reference only; not built or run) | `docs/research/components/` | Apache-2.0 ([NOTICE](docs/research/components/NOTICE.md)) | 2023 Vercel, Inc. |

The OFL lets fonts be bundled and redistributed with software, provided the license travels with them, which is
why each has its license file beside it (the license texts are the ones Google Fonts publishes for these
families).

## Downloaded when ADAM runs (not included)

| What | Used by | License |
|---|---|---|
| [Xenova/all-MiniLM-L6-v2](https://huggingface.co/Xenova/all-MiniLM-L6-v2), pinned revision | `memory/semantic_index.py` (embeddings) | Apache-2.0 |

## Python dependencies (installed separately)

| Package | License |
|---|---|
| networkx | BSD-3-Clause |
| numpy | BSD-3-Clause, with bundled parts under 0BSD, MIT, Zlib and CC0-1.0 |
| onnxruntime | MIT |
| tokenizers | Apache-2.0 |
| huggingface-hub | Apache-2.0 |
| flask | BSD-3-Clause |
| rich | MIT |
| pydantic | MIT |
| cactus-needle | Apache-2.0 |
| [yewtree](https://github.com/AdamMostofi/yewtree) (the memory engine) | MIT; its own dependencies are listed in its [THIRD_PARTY.md](https://github.com/AdamMostofi/yewtree/blob/main/THIRD_PARTY.md) |

All of these are compatible with ADAM's MIT license.
