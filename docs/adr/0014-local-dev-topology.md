# ADR-0014: Local development runs a small stand-in, with GPU workloads sequenced

## Context
Local hardware is an **NVIDIA RTX 4080 with 12 GB VRAM** and **23 GiB of RAM** in WSL2.
The target answering model, Qwen3-Coder-30B-A3B-Instruct, is a fixed constraint (ADR-0012's
sibling constraint, recorded in SPEC §10.1).

## Decision
Local development serves a small Qwen (`Qwen3-8B-AWQ`, or `Qwen3-4B-Instruct-2507` for more
headroom) with tool calling enabled. Embeddings run on **CPU**. Document conversion and picture
description run on the GPU **only during an ingestion window**, never while the LLM is loaded.

## Rationale
The target model does not fit and cannot be made to fit:

- 30.5B parameters is ~17–20 GB at 4-bit before KV cache. 12 GB is not close.
- The MoE architecture (~3B active) reduces compute, not the memory floor: all experts must be
  resident.
- RAM offload fails on the same arithmetic. A Q4 GGUF is ~18 GB, and the 23 GiB must also hold
  WSL, Docker running OpenSearch and Postgres, and the Python processes.

This is not a compromise forced by hardware; it is the plan already agreed. Local exists to
prove plumbing, and answer quality is measured remotely.

## Vision models: two roles, corrected
`granite-docling-258M` (530 MB — 258M parameters, siglip2-base-patch16-512 backbone,
Granite-165M decoder, document images to 2048×2048 via dynamic patching) is docling's
**document conversion** VLM. It produces layout, tables and formulas as DocTags. It does not
write a German description of a Kontextdiagramm.

The **picture-description** job required by ADR-0010 needs a general vision-language model of
the granite-vision-2b class, roughly 2–3 GB at fp16, configured through docling's
picture-description hook. Earlier drafts said "granite VLM" and conflated the two.

Both fit in 12 GB comfortably. The constraint is not size, it is concurrency.

## Consequences
- **Ingestion and serving never run simultaneously.** Ingestion is already a separate process
  (ADR-0005), so this is a `make` target that expects the LLM stopped, not new architecture.
- Tool calling is enabled locally (`--enable-auto-tool-choice --tool-call-parser hermes`) even
  though the prototype has no agent loop, because the endpoint contract must match remote.
- Pinned identical across local and remote: system prompt, German answer format with
  citations, tool schema, retrieval contract, generation parameters. The swap is one env var.
- **Never tune prompts against local output quality; never quote a metric produced locally.**
- Embeddings on CPU is a deliberate placement, not a fallback: it keeps VRAM free and is fast
  enough for 205 pages.

## WSL specifics
`vm.max_map_count=262144` is required or OpenSearch will not start. Set the OpenSearch heap
explicitly (`-Xms2g -Xmx2g`); the 1 GB default is too small with k-NN, which also uses off-heap
native memory. Disable container swap, set `memlock` unlimited, and verify `.wslconfig` actually
grants the 23 GiB.
