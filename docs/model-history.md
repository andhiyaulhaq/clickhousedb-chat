# Model history

Five fine-tuned versions of Qwen2.5-Coder (Indonesian question → ClickHouse SQL) were trained, all 4-bit (Q4_K_M GGUF) so they run in Ollama within 3 GB. Only **`text2sql-3b-v3`** is kept in this repo and in use; its profile, usage and limits are in `models/text2sql-3b-v3/README.md`. The older four stay in the original project (`slm-text2sql-clickhouse`) for comparison and rollback. Training and scoring steps are in `docs/training.md`.

## Versions
| Version | Ollama name | Base | File | Training data | Epochs | Train time (T4) |
|---|---|---|---|---|---|---|
| 1.5b-v1 | `text2sql` | Qwen2.5-Coder-1.5B | 0.99 GB | 1,211 pairs, first labels (before rules 10-12) | 3 | ~20 min (estimate) |
| 1.5b-v2 | `text2sql-v2` | Qwen2.5-Coder-1.5B | 0.99 GB | 1,211 pairs, relabelled with rules 10-12 | 3 | ~20 min (estimate) |
| 3b-v1 | `text2sql-3b` | Qwen2.5-Coder-3B | 1.93 GB | same 1,211 pairs as 1.5b-v2 | 3 | 36 min |
| 3b-v2 | `text2sql-3b-v2` | Qwen2.5-Coder-3B | 1.93 GB | 3,237 pairs (+ round 1 targeted data) | 2 | 61 min |
| **3b-v3** | `text2sql-3b-v3` | Qwen2.5-Coder-3B | 1.93 GB | 4,256 pairs (+ round 2 targeted data) | 3 | 116 min |

All use LoRA (rank 16, learning rate 2e-4, loss on the SQL answer only) via Unsloth, the same system prompt, ChatML template, temperature 0 and 2,048-token context. Memory in Ollama is about 1.1 GB for the 1.5B models and about 2.1 GB for the 3B models; speed on CPU is about 4 s and 6 s per query.

## Accuracy
Scoring is defined in `docs/training.md`. The Ollama column is the one that counts.

| Version | Colab (unquantized) | Ollama strict / lenient, dev set | Ollama, holdout |
|---|---|---|---|
| 1.5b-v1 | 60.4% | 55.2% / 60.4% (47.0% / 50.7% on the corrected labels) | not run |
| 1.5b-v2 | not recorded | 64.9% / 66.4% | not run |
| 3b-v1 | 70.9% | 70.9% / 73.1% | not run |
| 3b-v2 | 77.6% | 77.6% / 78.4% | not run |
| **3b-v3** | 91.0% | **85.8% / 86.6%** (86.6% / 87.3% with retry) | **89.5% / 92.5%** (88.0% / 91.0% on the 2026-10-25 re-run) |

Six dev questions were reworded between 3b-v1 and 3b-v2 to remove ambiguity (on the old wording 3b-v2 scored 75.4% strict), so early rows are not exactly comparable. Scoring also changed once: the same columns in a different order now count as strict-correct.

## What changed between versions
- **1.5b-v1:** first model. Labels were inconsistent about which columns to return, so it scores lower on the corrected labels.
- **1.5b-v2:** same questions, relabelled with consistent rules (default listing columns, id + name per entity, rounding, time buckets).
- **3b-v1:** same data as 1.5b-v2 on the larger base: +6 points.
- **3b-v2:** 2,000 more pairs aimed at the weak categories (window functions, 3-table joins, subqueries, dates) found by auditing 3b-v1 failures.
- **3b-v3:** 1,000 more pairs aimed at the remaining failure patterns (default columns, invented filters, row multiplication when joining two fact tables, invalid ClickHouse SQL, date comparisons, domain words like "forecast"). Eval loss was still falling at epoch 2, so 3 epochs.
