# PDF RAG Study Tool

A local RAG (Retrieval-Augmented Generation) pipeline for studying from documents that exceed an LLM's context window. Ingest PDFs, DOCX, and XLSX files into a vector store, then **query**, **summarize**, **teach**, **quiz**, or **chat** against the material — with page-level citations on every answer.

Generation runs through the Claude Code CLI by default (subscription plan limits, no metered API billing), with an optional Anthropic SDK backend behind a double opt-in.

## Architecture

```
                        INGEST                                RETRIEVE
 PDF/DOCX/XLSX ─▶ pdf_parser ─▶ section-aware ─┬─▶ BGE-M3 ─▶ ChromaDB ──┐
                 (docling +       chunker      │   (1024-d vectors)     │
                  PyMuPDF +                    └─▶ BM25 keyword index ──┤
                  OCR fallback)                                         ▼
                                                          Reciprocal Rank Fusion (k=60)
                                                                        │
                                                          cross-encoder rerank (top 30)
                                                                        │
                                                            top-10 context block
                                                                        ▼
                                                     Claude (CLI) ─▶ answer + [source, p. X]
```

Per-query flow:

1. Embed the query with **BGE-M3** (optionally augmented by **HyDE**: a short hypothetical answer whose embedding forms a third retrieval channel).
2. Pull 50 candidates from **ChromaDB** (cosine) and 50 from **BM25** (keywords).
3. Merge with **Reciprocal Rank Fusion**, rerank the top 30 with the **BAAI/bge-reranker-v2-m3** cross-encoder.
4. The top 10 chunks become the context block; answers must cite `[source, p. X]`.
5. Citations are validated for fabrication (`citations.py`) and claim attribution (`citation_support.py`).

All chunks live in a single ChromaDB collection with `source` / `project` metadata, so per-document and per-project scoping is a filter, not a separate index.

## Design decisions

- **Hybrid, not pure-dense.** BM25 catches the exact terms (names, numbers, acronyms) that embeddings fuzz over; RRF fuses the two rankings without score normalization because it is rank-based.
- **Cheap wide nets first, one expensive judge last.** The 50+50 candidate pulls cost milliseconds; the slow cross-encoder only ever sees 30 pairs. Measured: reranking rescues answers that fusion alone ranks just outside the window.
- **One collection, metadata scoping.** Per-document and per-project filters instead of per-document indexes, so query latency does not grow with corpus size.
- **Idempotent ingest.** Chunk IDs are content-addressed (`{project}::{source}::{sha1}`), so re-ingesting a file is a no-op and the same source can live in two projects.
- **A single choke point for LLM calls.** `claude_bridge.py` owns backend choice, billing safety (the CLI backend strips `ANTHROPIC_API_KEY` so nothing is silently metered), and token accounting.
- **Citations are verified, not trusted.** A fabrication check (cited page exists and matches) and a separate attribution check (cited chunk actually supports the claim) — the two are never conflated.
- **Evaluation is part of the pipeline.** A frozen baseline, a regression gate, held-out questions never tuned on, and planted-defect probes for the LLM judges themselves.

## Installation

```
python -m pip install -r requirements.txt
```

First runs download models that are then cached forever: BGE-M3 (~2.3 GB), the reranker (~600 MB), docling layout models (~1 GB), and easyocr (~500 MB, only if a scanned PDF triggers the OCR fallback).

## Usage

```
python rag.py ingest path/to/file.pdf          # single document
python batch_ingest.py path/to/folder          # bulk ingest, recursive

python rag.py list                             # what's in the store
python rag.py query "your question"
python rag.py query "..." --doc <source> --project <name>
python rag.py teach "topic"
python rag.py summarize --doc <source>
python rag.py quiz -n 10 --topic "topic"
python rag.py chat
python rag.py delete <source>
```

`<source>` is the filename without extension. `--verbose` / `-v` enables DEBUG retrieval logging.

## Use with a local model (Open WebUI)

`tool_server.py` serves retrieval as an OpenAPI tool, so a model you run yourself
can search documents that are too large to attach to a chat. The model calls
`search_documents`, receives the top passages with `[source, page N]` headers, and
writes the cited answer itself. No Claude call is involved. It works with any
OpenAI-compatible model server that supports tool calling (vLLM, llama.cpp,
Ollama) behind Open WebUI.

```
python tool_server.py                                   # loopback only, no auth
PDFRAG_SERVER_TOKEN=<token> python tool_server.py --host 0.0.0.0
python tools/probe_local_model.py                       # model + tool server, no Open WebUI
```

- Two tools are exposed: `search_documents` (query, optional `project` /
  `document` scope, `top_k`) and `list_documents`.
- Listening on anything other than loopback requires `PDFRAG_SERVER_TOKEN`; the
  server refuses to start without it. Clients send it as a bearer token.
- HyDE is off on this path (it needs the Claude CLI), so retrieval is dense +
  BM25 + rerank. The eval numbers in this README were measured with HyDE on and
  do not cover this configuration.
- Ingest stays a CLI step, and the server must be restarted after it: the running
  process holds the vector index in memory.
- `tools/probe_local_model.py` plays Open WebUI's part: it sends eval questions to
  the model server with the tool server's tools, runs the model's tool calls, and
  prints each call next to the expected answer. It flags any answer given without a
  `search_documents` call. Use it to tell a model-side failure from an Open WebUI
  configuration problem. Its questions are about the capstone corpus.

### Setup on an NVIDIA DGX Spark

Verified on a DGX Spark (GB10, CUDA 13.0, aarch64, Ubuntu 24.04) with
Qwen3.8-Flash-Next-NVFP4 served by vLLM and Open WebUI 0.11.4, both in Docker
with host networking. Retrieval ran on the GPU. The probe's three questions all
went through `search_documents` and got the right answer (one page was cited as a
range, pages 7-8 for page 8), and the same kind of question asked in Open WebUI
produced a `search_documents` call and the correct cited answer.

1. **Clone and install.** Install the CUDA build of torch first: on aarch64 a
   plain `pip install torch` can give a CPU-only build. The constraints file then
   stops a later install from silently replacing it.

   ```
   git clone https://github.com/curasinan/pdf-rag.git && cd pdf-rag
   python3 -m venv .venv && source .venv/bin/activate      # Ubuntu may need python3.12-venv
   pip install torch torchvision --index-url https://download.pytorch.org/whl/cu130
   python -c "import torch; print(torch.cuda.is_available(), torch.cuda.get_device_capability())"
   python -c "import torch, torchvision; print(f'torch=={torch.__version__}'); print(f'torchvision=={torchvision.__version__}')" > .venv/torch-pin.txt
   pip install -r requirements.txt -c .venv/torch-pin.txt
   ```

   The check must print `True (12, 1)`.

2. **Copy the documents.** `git clone` brings code only. Copy the document folders
   into `sources/<project>` (gitignored), not a copy of the whole project: only
   `.pdf`, `.docx` and `.xlsx` files are ingested, so a project copy pulls in
   generated deliverables. From Windows PowerShell, with an SSH host alias `spark`:

   ```
   scp -r "C:\path\to\folder" spark:pdf-rag/sources/<project>
   ```

   A folder copied from Windows can arrive without write permission on its
   directories, which makes moving it fail with "Permission denied";
   `find sources -type d ! -writable -exec chmod u+w {} +` fixes it.

3. **Ingest** (inside `tmux`, so a dropped SSH session does not stop it):

   ```
   python batch_ingest.py sources/<project> --project <project>
   python rag.py projects
   ```

   `batch_ingest.py` refuses to start when two files share a name without the
   extension (`plan.pdf` and `plan.docx`), since one would overwrite the other.

4. **Check memory.** Memory is shared between the model and retrieval. Measured on
   the Spark: vLLM held about 85 GiB, the tool server about 4.4 GiB, and 18 to 24 GiB
   stayed available. If memory runs out, the kernel kills the largest process, which
   is the model server. `nvidia-smi` reports total memory as "Not Supported" on the
   Spark; use `free -h`, and `nvidia-smi --query-compute-apps=pid,process_name,used_memory --format=csv`
   for per-process use.

5. **Check the model server.** vLLM accepts tool calls only when started with
   `--enable-auto-tool-choice` and a `--tool-call-parser`. For Qwen3.8-Flash-Next
   the working flags were `--tool-call-parser qwen3_xml --reasoning-parser qwen3`.
   See what a container was started with:

   ```
   docker inspect -f '{{json .Config.Cmd}}' <vllm-container>
   ```

   A default search returns about 15K tokens, so the context window must be at
   least 32K. vLLM sets it with `--max-model-len` and rejects longer requests.
   Ollama is different: it can load a model with less context than advertised and
   truncates input silently, so check `ollama ps` (CONTEXT column) and set
   `num_ctx` if it is below 32K.

6. **Start the tool server.** Check how Open WebUI is networked:

   ```
   docker inspect -f '{{.HostConfig.NetworkMode}}' <open-webui-container>
   ```

   With `host`, the container shares the Spark's network, so keep the default
   loopback bind and no token:

   ```
   python tool_server.py
   ```

   With a bridge network, `localhost` inside the container is the container, so
   bind to the network with a token and use the Spark's LAN address or the bridge
   gateway (`docker network inspect bridge -f '{{(index .IPAM.Config 0).Gateway}}'`):

   ```
   export PDFRAG_SERVER_TOKEN="$(openssl rand -hex 32)"
   python tool_server.py --host 0.0.0.0
   ```

   Either way, wait for `tool server ready: device=cuda:0, N chunks indexed`, then
   confirm the container reaches it:
   `docker exec <open-webui-container> curl -s http://<address>:8765/health`
   prints `{"status":"ok"}`.

7. **Test the model side.** `python tools/probe_local_model.py` should end with
   `3/3 questions searched the documents.` If a question shows
   `!! no search_documents call`, the problem is the model server, not Open WebUI.

8. **Register the tool server in Open WebUI, as admin.** Profile menu → Admin
   Panel → Settings, then the tool server section (*External Tools*, *Tools* or
   *Integrations* depending on version). Add a connection of type OpenAPI with URL
   `http://127.0.0.1:8765` (or the address from step 6), path `openapi.json`, and
   auth None (or bearer with the token). Saving makes the server log
   `GET /openapi.json 200`; if that line does not appear, Open WebUI did not reach
   the server. A server added under a user's own Settings is called by the
   *browser*, where that address points at the user's own machine. See the
   [Open WebUI docs](https://docs.openwebui.com/features/extensibility/plugin/tools/openapi-servers/open-webui/).

9. **Enable it in a chat.** In Open WebUI 0.11.4 the tools are behind the icon to
   the right of `+` in the message box (the `+` menu only attaches files). Native
   function calling is the default since 0.10.0. Each question that uses the tool
   adds a `POST /search_documents 200` line to the server log
   (`grep uvicorn.access data/logs/rag.log`); an answer without one came from the
   model's own knowledge, not the documents.

10. **Keep it running.** `deploy/pdfrag-tool-server.service` runs the server as a
    systemd user service: it starts at boot, restarts on failure, and is the first
    process the kernel kills if memory runs out (instead of the model server). Stop
    any copy started by hand first (the port must be free), then:

    ```
    mkdir -p ~/.config/systemd/user
    cp deploy/pdfrag-tool-server.service ~/.config/systemd/user/
    systemctl --user daemon-reload
    systemctl --user enable --now pdfrag-tool-server
    sudo loginctl enable-linger "$USER"
    ```

    The unit assumes the repository is at `~/pdf-rag` and serves on loopback with
    no token (step 6, host networking). It runs Hugging Face in offline mode, so
    start the server by hand once first to download the models. Logs:
    `journalctl --user -u pdfrag-tool-server`.

Observed with Qwen3.8-Flash-Next: each answer took 40 to 65 seconds with reasoning
on. Citations name chunk page ranges, so a fact on page 8 may be cited as pages 7-8,
and the model sometimes adds small unsupported details (it once miscounted the
ingested documents). Check the page before relying on it.

After ingesting new documents, restart the server: `systemctl --user restart pdfrag-tool-server`, or stop and start it by hand.

## Evaluation

The pipeline ships with a full eval harness (`eval/`):

- 20-question easy regression set plus a 25-question hard set with per-source gold pages, required phrases, and expected numbers (10 questions held out from all tuning).
- LLM judges with evidence-only 5-axis scoring, multi-run medians, span-aware critical-error voting, and planted-defect probes (`tools/probe_judge.py`) that must pass after any judge edit.
- A regression gate (`eval/gate.py`) comparing runs against a frozen baseline — recall/MRR/nDCG tolerances plus blocking on *new* critical errors only.
- A three-arm ablation study (hybrid RAG vs whole-corpus context vs agentic file access) with paired statistics — see `ABLATION_WRITEUP.md`.

```
python -m pytest tests/ -m "not slow"          # 95 fast tests
python eval/run.py --hard                      # full hard eval
python eval/gate.py --current eval/results_hard.json --baseline eval/baseline.json
```

## Repository map

| Area | Files |
|---|---|
| CLI + orchestration | `rag.py`, `pipeline.py`, `batch_ingest.py` |
| Tool server (local models) | `tool_server.py`, `tools/probe_local_model.py` |
| Parsing + chunking | `pdf_parser.py`, `config.py` |
| Retrieval | `retrieval.py`, `embeddings.py`, `vectorstore.py`, `bm25.py`, `reranker.py`, `hyde.py` |
| Generation | `claude_bridge.py`, `prompts.py` |
| Citation checks | `citations.py`, `citation_support.py`, `groundedness.py` |
| Eval harness | `eval/`, `tools/` |
| Documentation | `FULL_PICTURE.md` (what/why + project history), `ABLATION_WRITEUP.md` (retrieval-strategy study) |

## Notes

- Source documents and runtime data (`sources/`, `data/`) are not committed; the vector store and BM25 index are rebuilt by re-ingesting.
- OCR is fallback-only and per-page; DOCX/XLSX page numbers are synthetic.
- The default backend never touches a paid API key — `claude_bridge` strips `ANTHROPIC_API_KEY` from subprocess environments by design.
