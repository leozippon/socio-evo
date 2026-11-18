# Running the research laboratories

This guide owns deployment procedures. The [IR laboratory protocol](../../docs/ir-laboratory.md) describes the new dated profile; the [institute protocol](../../docs/research.md) describes the preserved institute run. Both use local Qwen inference on host GPU 0 and CUDA/PyTorch research on host GPU 1. Preparation and acceptance probes do not start a formal experiment.

All source deployment, runtime state, probes and generated reports stay on Zenith under `/project_c20250210/260903018`. The launcher refuses local or relative run roots. The active model-enabled IR continuation uses `socio-evo-ai-lab/pit-models-20261116-r1` under that storage root. Its original dated IR branch remains in `socio-evo-ai-lab/pit-lab-20261115-r1`, and the stopped institute remains in `socio-evo-ai-lab/deployment-20261115-r1`. The interrupted initial laboratory and completed town/academy pair are preserved separately.

## Prepare services

Install the committed source with Python 3.11+ and `pip install -e '.[research,dev]'`. The existing serving interpreter is `/personal_fast_storage/qwen-serving/venv/bin/python`; it reads Qwen3.8-27B-FP8 weights from `/public_fast_storage/lty26/models/Qwen3.8-27B-FP8`. Check the selected GPUs before starting services. From the deployed checkout, the current serving command is:

```sh
DEPLOY=/project_c20250210/260903018/socio-evo-ai-lab/pit-models-20261116-r1
LD_LIBRARY_PATH=/personal_fast_storage/qwen-serving/cuda-compat/usr/local/cuda-12.9/compat \
  /personal_fast_storage/qwen-serving/venv/bin/python -m ops.research.model_service \
  --root "$DEPLOY" --gpus 0 --port 8041 --max-model-len 262144 \
  --max-num-seqs 8 --kv-cache-dtype auto
```

Keep the foreground service in a persistent remote terminal or process supervisor. Tensor parallelism follows the single selected GPU; the server can hold eight sequences while the laboratory has four concurrent residents. The service writes `model-status.json`, `model.log` and mode-0600 `model.env`/`model-api-key` under the deployment root. A `ready` state includes a real tool-call/continuation probe. A process lock prevents concurrent owners of that root. After observing a run in the running state, the service stops when all watched runs are terminal; pre-existing completed or interrupted manifests do not stop a freshly restarted service during resume preflight.

Build the research image independently of the model-serving environment:

```sh
docker build -t socio-evo-ai-institute:20261115 -f ops/research/Dockerfile.paper .
```

The paper image extends the validated `socio-evo-ai-lab:20261114` CUDA image and adds `latexmk`, pdfLaTeX, BibTeX and common mathematics, algorithm, table and figure packages. The base image is built with `Dockerfile.cuda` when needed; extending it avoids downloading PyTorch again. Build-time temporary files use `/tmp`; the running container retains its persistent `/runtime` paths. Research containers mount shared files at `/research`, read-only evidence at `/records`, and a separate persistent runtime at `/runtime`. Ordinary `pip install` targets `/runtime/python`; model downloads and caches also live outside research Git. The scientific state required for a result must stay under `/research`, including training checkpoints and environment/version records.

Load `LIGHTING_API_KEY` and `GITHUB_TOKEN` from the IR deployment's private mode-0600 `credentials.env`, and the local model credential from `model.env`. The older non-PIT profile uses `TAVILY_API_KEY` instead of GitHub. Credentials stay outside the source checkout and research containers:

```sh
set -a
. "$DEPLOY/credentials.env"
. "$DEPLOY/model.env"
set +a
export PYTHONDONTWRITEBYTECODE=1
```

Every normal launch first runs preflight with the actual profile: actor tool calling and continuation, a structured external judge reply, enabled browsing routes, host-GPU identity, a CUDA optimizer step and saved tensor loading in another container. The old profile checks Tavily/curl; the dated profile checks arXiv/GitHub and disabled container networking. Conference profiles additionally compile a LaTeX document containing a generated figure, table, algorithm, cross-reference and BibTeX citation, and check the PDF and resolved references. `--preflight-only` is available for isolated diagnostics; it need not precede a normal launch. Separate acceptance probes verify the exact resident-facing CUDA example and a real conference review with grounded citations. Semantic Scholar is recorded as disabled, not passed. A failed check prevents launch. Acceptance requires those concrete operations, not merely `nvidia-smi` or successful package imports.

## Historical institute launch

These commands describe the stopped institute. Do not resume it as part of the IR experiment. The default profile runs through the day-70 checkpoint:

```sh
DEPLOY=/project_c20250210/260903018/socio-evo-ai-lab/deployment-20261115-r1
python -m ops.research.run_lab --runs-root "$DEPLOY/runs" --seed 20260302 --until-day 70
```

The first seven days remain free of a research commission. The task appears at 07:00 on day 8; the first paper review is day 28, followed by days 49 and 70. There is no proposal reward. The cycle scheduler has no fixed round limit, but this deployment is planned for 70 days, not indefinite operation. Set a longer `days` value before launching if needed. For an explicitly staged run, `--until-day 7` stops before the commission and `--resume --until-day 70` continues with the same frozen configuration. The model service must be available during launch and resume. `--gpu device=1` is already the research default; keep GPU 0 reserved for inference. The laboratory launcher never starts a second institutional arm. It locks the control directory, refuses a live duplicate, freezes its configuration and does not silently restart a failed run.

The control directory is `runs/lab-seed-20260302/`; `preflight.json` there records enabled checks. The actual experiment, once launched, is `runs/ai-institute-seed-20260302/`, with its own manifest, checkpoints, research Git history, resident files, raw judge reviews and persistent runtime. A control directory created by `--preflight-only` is not evidence of a launched experiment. Configuration changes require a new run rather than silently changing a resumed one; changing `days` on an already frozen run is not a supported extension mechanism.

For a separate read-only viewer, use a free remote port and SSH forwarding:

```sh
python -m frontend.research_server --runs-root "$DEPLOY/runs" --site "$DEPLOY/site" --port 8921
```

Forward local port 8921 to remote `127.0.0.1:8921`; the original laboratory viewer remains on 8920. The viewer reads remote files directly and remains waiting before a run exists. Keep viewer data and all later analysis on Zenith; do not mirror experiment outputs into the checkout.

## Original dated IR profile

The commands below describe the original dated profile. Its November 15 run is now preserved; the active model-enabled continuation uses its own generated launch profile and root, described in the next section.

Use a separate deployment and run root for `experiments/configs/ir-lab.yaml`. Do not resume the old institute with this profile or reuse its scientific/runtime directories. `research_background` and `conference_calendar` resources are expanded into the frozen run configuration, so later edits cannot silently change a resumed world. The [new protocol](../../docs/ir-laboratory.md) owns the calendar and funding rules.

The model and judge credentials remain `VLLM_API_KEY` and `LIGHTING_API_KEY`. PIT does not require Tavily or Semantic Scholar credentials. A host-only `GITHUB_TOKEN` is optional for public GitHub API throughput; anonymous operation can encounter low rate limits. Never put it in resident prompts, recorded commands, images or mounted runtime caches. The gateway sends it only to the GitHub API.

PIT preflight searches and opens both real providers, downloads an arXiv PDF, records version provenance, verifies the research container's disabled network, and retains the actor, judge, GPU and LaTeX probes. Missing services fail explicitly rather than enabling unrestricted networking. Installed scientific libraries remain usable offline; preflight does not promise that arbitrary model-hub weights, pip packages or datasets can be downloaded. The source audit and gateway receipts must be reviewed before treating this as a historically valid dataset.

From the new deployed checkout, after arranging the model-service handover:

```sh
PIT_DEPLOY=/project_c20250210/260903018/socio-evo-ai-lab/pit-lab-20261115-r1
python -m ops.research.run_lab --config experiments/configs/ir-lab.yaml \
  --runs-root "$PIT_DEPLOY/runs" --seed 20260302
```

The normal launch includes full preflight. For an interrupted run, add `--resume` with the same configuration and root; do not rerun a live controller. A deliberate `--until-day 7` is only a staged stop, not required for the seven-day free-life protocol. Omitting `--until-day` selects the latest complete lived-day checkpoint already reached in real Beijing time, capped by the frozen 306-day horizon. A checkpoint falls at 04:30 on the following calendar date; the launcher accounts for that boundary. An explicit later date is refused because its research materials do not yet exist. Resume later with the same configuration to advance toward December 31. Do not copy incomplete future-day data into the library.

The new run name is `ir-lab-pit-seed-20260302`; its control directory remains `lab-seed-20260302` under the **new** runs root. Keep the model supervisor associated with that deployment once handing over: the old deployment's supervisor can stop its owned model when its old run finishes. Starting another formal run without arranging that ownership is not a validated launch.

Run the new read-only viewer with `python -m frontend.research_server --runs-root "$PIT_DEPLOY/runs" --site "$PIT_DEPLOY/site" --port 8922` and forward local 8922 to remote 127.0.0.1:8922. Keep the historical institute viewer on 8921. The viewer automatically displays the dated clock, conference desk, submission states and released events for calendar profiles. Source/PDF files, immutable submission receipts, reviewer inputs, rebuttals, decisions and living stipends remain on Zenith. A review scheduled after the configured horizon remains pending.

For an isolated real judge protocol check, `python -m ops.research.check_conference --config experiments/configs/ir-lab.yaml --output <new-project-storage-directory>` exercises three initial reviews, an author response, three updated reviews and one area-chair decision. It allows at most seven calls, verifies restoration before and after the decision, and never invokes residents, GPUs or a real conference. Its manuscript is explicitly an inadequate synthetic infrastructure test; a passing receipt is not scientific validation.

November 15 preparation receipts are under `/project_c20250210/260903018/socio-evo-ai-lab/pit-preparation-20261115`. `conference-acceptance-r1/receipt.json` passed seven real `gpt-6.1-sol` calls and two restore checks with no additional calls or grants. The synthetic paper was rejected. `browser-acceptance/final/acceptance.json`, completed at 22:35:39 Beijing, records the final public-only gateway passing actual arXiv historical search, versioned reading, PDF download/text extraction, and authenticated GitHub search, historical README and archive download. The initial anonymous GitHub quota failure and arXiv API failure are retained; the gateway now uses official arXiv HTML, not the inaccessible export API. The supplied GitHub credential is kept in the private mode-0600 `github.env` at this preparation root and must be loaded only into the host gateway/launcher environment. These preparation probes are separate from the formal launch record below.

## Model-enabled continuation

The [model library guide](../../docs/model-library.md) owns resident usage. A continuation can explicitly enable `town.research.models_enabled`, set `inference_python` to the existing host serving interpreter, and configure `model_download_timeout_s` (default 3600). Ordinary commands and inference retain the profile's command timeout. The interpreter and GPU selector are operator configuration, never resident-supplied commands.

The host gateway reads `HF_ENDPOINT`, defaulting to the official Hugging Face endpoint. An alternate endpoint is explicit and appears in model provenance; there is no silent fallback. Commit history selects a full SHA before fetching files. LFS SHA-256 and Git blob hashes verify the pinned bytes. Large weights live in the run's private `model_cache`; `research/records/models.json` admits exact snapshots, which the shell mounts read-only under `/models/<model_id>`. The research container remains offline.

For the accepted Zenith continuation, the controller environment includes:

```sh
export HF_ENDPOINT=https://hf-mirror.com
export PYTHONPATH="$DEPLOY/code:$DEPLOY/host-deps"
export LD_LIBRARY_PATH=/personal_fast_storage/qwen-serving/cuda-compat/usr/local/cuda-12.9/compat
```

The vLLM worker uses the compatible serving interpreter but owns a separate process group on physical GPU 1. Set the same CUDA compatibility `LD_LIBRARY_PATH` used by the actor service. The worker receives no API credentials, uses local files, applies the model chat template by default, and releases its GPU processes on completion, cancellation or timeout. Its persistent diagnostics stay in the run's private `model_inference_logs`, outside research Git. The actor service on GPU 0 remains a separate owner.

Changing capabilities mid-experiment requires a recorded continuation: stop the source, retain all source files including later live activity, fork a complete checkpoint into a new root, and record source/config/research identities in lineage. Preserve the old viewer and give the continuation its own viewer. The new model-service supervisor must watch the new root. Do not modify the source run's frozen configuration or share writable runtime directories between branches. Capability delivery is once-only and waits until the ordinary research commission is active.

The November 16 host could not connect directly to the official Hub because its DNS response was incorrect and verified-address TLS was reset. Standard HF client headers made the configured `HF_ENDPOINT=https://hf-mirror.com` usable directly. The real Qwen2.5-0.5B-Instruct download at cutoff March 20 selected `7ae557604adf67be50417f59c2c2f167def9a775` (September 25, 2024), verified all ten files and the 988,097,824-byte safetensors SHA-256 against official metadata, and rejected that commit under a September 20, 2024 cutoff. The download receipt is `pit-model-preparation-20261116/hf-acceptance-r1/acceptance.json`; the temporary Mac proxy used for official metadata diagnosis is not required by that direct download. This receipt alone does not certify GPU inference.

Full acceptance must exercise the actual research model tool, mount the same downloaded snapshot in the offline scientific container, and generate real outputs with vLLM on GPU 1. Check the physical UUID, file hashes, future-revision rejection, model-service health and process cleanup. A passed import or a downloaded pointer file is insufficient. All acceptance data and generated files remain on Zenith, separate from residents' scientific results.

The November 16 end-to-end model acceptance passed at 18:25:46 Beijing under `pit-models-20261116-r1/preflight/models-r2/receipt.json`: actual model-tool admission, read-only offline Docker/Transformers loading, a two-prompt vLLM batch on physical GPU 1, and two checkpoint restoration checks. The worker reported vLLM 0.28.0+cu129, Torch 2.13.0+cu129 and Transformers 5.19.0; GPU 1 returned to idle afterward. The first attempt exposed Transformers' default structured chat-template return, fixed by explicit token-list output in `b7ca2f9`; its failed record remains in `models-r1`. The tiny acceptance model's incorrect dense-retrieval answer is retained and is not counted as a scientific result. A separate basic-generation receipt confirms normal arithmetic and translation output.

## Deployment status and history

The current continuation runs source `e8a6b2401517a6cb64b7bd32edde957dbbc698fd`, enabling independent parallel conference submissions. On November 18, a watcher selected the next complete checkpoint, day 89 (May 29, 04:30:02), then gracefully stopped the old controller with no subsequent partial-day action. `backups/parallel-submissions-20261118T111656Z/preservation.json` records the 206,295,040-byte archive and five audit refs. Controller PID 3616060 resumed the same run from that checkpoint at 19:31 Beijing; normal preflight passed at 19:31:27. Qwen supervisor/model PIDs were 3614971/3614977. Acceptance at 19:35:13 confirmed all four residents received one policy notice and produced fresh replies, the old CIKM/EMNLP entries and historical guides remained unchanged, and the world progressed into day 90 without new runtime errors. A non-stopping HTTP-client cleanup warning remains recorded. The new handbook is `records/conferences-v2.md`; the notice is `records/conference-policy-v2.json`. Frozen scientific configuration, source chronology checks and day-260 stop target are unchanged. Authoritative receipts are under `preflight/parallel-submissions-checkpoint-watch/{controller-launch,schema-check,acceptance}.json`. The original manifest creation revision remains historical; deployment metadata and the resume receipts identify the actual running source. The entries below describe earlier launches.

On November 16, neutral model-selection guidance was deployed from clean source `07da8862bea7e344751972557a501b5e989b7d9e` into the same model-enabled run. Controller PID 3410230 started at 21:37:25 Beijing and full normal preflight passed at 21:37:51. The frozen scientific configuration and Hugging Face PIT checks are unchanged. Before resume, `backups/help-v2-20261116T133239Z/preservation.json` recorded a 66,119,680-byte archive of agent working trees and original logs, the complete day-22 checkpoint, and audit refs preserving the research and four resident HEADs. Resume returns to day 23 at 04:30:01; the later partial-day trajectory remains archived rather than being treated as resumed state. The original capability notice remains byte-identical; the once-only correction is stored separately as `records/models-help-v2.json`. All four residents had received it by 21:38:59. Older PIDs and source revisions below describe prior launches; the original run manifest's creation revision is not the continuation's running source revision.

The model-enabled continuation is `pit-models-20261116-r1/runs/ir-lab-models-seed-20260302`, with its viewer on port 8923. Its source IR branch stopped at 18:04:52 Beijing on November 16, retaining complete checkpoint 20 and later live records through day 21 at 16:46:34. Source viewer 8922 remains available. The exact selected Git ancestry was copied without partial-day refs, and the new world log ends at the checkpoint boundary; private runtime caches were copied separately with their non-checkpoint semantics recorded. `lineage.json` identifies source configuration, checkpoint, four agent revisions and research revision `083cd173b5da91b48c869e8357a1f15e09633877`.

The fork was prepared by `b101c89`; the actual continuation runs the corrected `b7ca2f9045417be6cb147746bdc77ec028e761cb`. Controller PID 3386208 began normal preflight at 18:45:43 Beijing; every check passed at 18:46:06 and the manifest became running. Actor supervisor PID 3380060 watches the new root; viewer PID 3380061 serves port 8923. `preflight/resume-launch.json` and `runs/lab-seed-20260302/preflight.json` retain the launch evidence. The simulation's existing interpreter loads deployment-local `host-deps` with Hugging Face Hub 1.33.0; the old shared environment was not changed. The model cache may be preseeded, but only residents' explicit model downloads admit snapshots into their checkpointed evidence.

Continuation acceptance at 18:51:27 Beijing is recorded in `preflight/resume-acceptance.json`. All four residents produced new replies and received the capability notice; Ravi autonomously called model search, download and generate, and Kofi called search. The world advanced into day 21 with increasing event sequence and simulated time. There were no new lapses, context overflows, tool errors or simulation ERROR/Traceback signals during acceptance. Preflight HTTP-client cleanup did emit a non-stopping `Event loop is closed` warning. Both viewer ports returned HTTP 200; the old run remained interrupted. The continuation targets day 260 within the unchanged 306-day horizon.

The original dated IR experiment `ir-lab-pit-seed-20260302` started fresh on November 15 at 23:10:59 Beijing (15:10:59 UTC), from clean source `8254ccc10cda2dbc42dc887f250816987bff8569` in `pit-lab-20261115-r1/code`, under controller/simulation PID 2197978. Its launch model supervisor/server PIDs were 2191316/2191811; the read-only viewer PID was 2191317 on port 8922. Its frozen horizon was 306 days and that launch targeted day 259 (November 14), before a later resume could advance into subsequent real dates. These are historical launch identities, not permanent PIDs.

Full preflight passed at 23:10:58 Beijing: Qwen tool calling/continuation, external `gpt-6.1-sol`, arXiv/GitHub historical search and reading at the March 1 cutoff, the version-5 Search-R1 PDF download, network-isolated CUDA training on physical GPU 1, checkpoint reload in a second container and LaTeX compilation. GPU 1 was verified by UUID `GPU-a44e8b8d-c044-47f5-3a9f-6c4243e85264`; GPU 0 remains reserved for inference. Preflight outputs remain separate from resident science. GitHub raw-file fetching was slow, approximately 18 seconds per request during acceptance, but completed without bypassing version checks. Receipts are `runs/lab-seed-20260302/preflight.json`, `preflight/launch.json` and `deployment.json` under the new root.

Startup acceptance at 23:13:42 recorded real replies from Mei/Aisha/Ravi/Kofi (12/13/9/5), event sequence growth from 10 to 37 and simulated time advancing from 07:06 to 07:50 on March 1. No response lapse, context overflow, tool failure or run traceback was found. Initial prompts and tools did not expose the future commission; background readings were present and the conference handbook remained unpublished. The browser/GPU checks were independent preflight, not early resident research actions. `preflight/launch-acceptance.json` retains these observations; the main agent also verified the live page through the local SSH forward, including all four residents and the dated clock.

The old institute was gracefully stopped on November 15 at 22:52:47 Beijing. Its manifest is `interrupted`, with no active simulation PID; checkpoint day 27 and subsequent live records through day 28 at 09:34:02 remain intact. The old model supervisor exited automatically. Its historical viewer on 8921 stays available, including the three distinct PDFs. Stop receipts are `deployment-20261115-r1/preflight/switch-to-ir-20261115/{stop-requested,stop-result}.json`.

The revised `ai-institute-seed-20260302` started on 2026-11-14 at 17:21:06 UTC (2026-11-15 01:21:06 Beijing time), from exact source `f93b367fdb64aadd30bc71ba88dc3cff6284f1d1` in `deployment-20261115-r1`. Startup acceptance confirmed a running manifest under PID 467061, four PhD residents with real model replies, and event growth from 37 to 44 over 20 seconds. No research commission, tools or future deadlines were present in their early inputs. Qwen uses GPU 0 under supervisor PID 463297 and server PID 463830; the read-only viewer is on 8921 under PID 464936. These PIDs describe the verified launch, not a permanent availability guarantee.

The final paper image is `socio-evo-ai-institute:20261115`, immutable ID `sha256:c2a262e5cc2ef890b13458b424d99ead102323782493ab95840cd9b0dc7955db`, with Dockerfile SHA-256 `44a30f2f0346b6e0aa139ec9b082a36919f13d5255be49cba206115f09ff006e`. Its real acceptance passed the exact resident-facing CUDA example, LaTeX compilation with generated figures and bibliography, and a real external conference review with confidence, revision requests and 25 verified exact citations. That review evaluated a clearly labeled synthetic infrastructure artifact, not a formal research result. The formal launcher then passed actor, judge, Tavily, curl, LaTeX, physical-GPU-1 CUDA training and cross-container checkpoint loading. A nonfatal HTTP client cleanup warning was recorded; there were no runtime lapses, context overflows or tool exceptions during launch acceptance.

Authoritative receipts are `build/image-build.json`, `preflight/conference-acceptance-r2/result.json`, `preflight/launch-acceptance.json`, `runs/lab-seed-20260302/preflight.json`, `launch.json` and `deployment.json` under the historical `deployment-20261115-r1` root. Earlier build and acceptance attempts remain preserved. The first LaTeX build inherited a runtime-only temporary directory and was corrected with build-only `/tmp`; the first acceptance script used an overly strict capitalization check for a BibTeX title, while its CUDA and LaTeX execution had succeeded. Neither correction changed the running experiment's code.

The PDF-enabled viewer runs from the separate `viewer-code-740d220` checkout, PID 1917494 at its verified November 15 19:54 Beijing deployment. Its historical-first-manuscript entry selects an exact source match in Git history, restoring separate access to the original 7-page paper alongside the 11-page second and 15-page third papers. Its paper tab lists the three available manuscripts and renders PDF pages through locally served PDF.js, including in the app browser. This historical viewer reads the preserved simulation from frozen source f93b367. Current acceptance is recorded in `preflight/viewer-history-20261115-740d220/acceptance.json`; the earlier PDF.js acceptance remains preserved separately.

On November 15, the original run resumed on the replacement host from its complete day-18 checkpoint, entering day 19, under PID 1196857 after the full preflight passed. The original run name, start time, source f93b367, frozen configuration and seed were retained; no new scientific run was created. Viewer 8921 was restored through SSH port 64295.

On the replacement host, the research image was rebuilt from the same Dockerfile chain because the new daemon had no images. Its new immutable ID is `sha256:12161bd136dc05b1feb103f5728ac2241695f8025d527ce5acbc44c41e387f46`; it is not a bitwise copy of the original image. The pinned PyTorch wheel and verified Torch/Transformers/Datasets/Accelerate versions match the recorded environment. Recovery build receipts and the private pre-resume snapshot remain under `recovery/new-host-20261115/`.

The initial experiment `ai-lab-seed-20260302`, in `deployment-20261114-r1`, was stopped at the user's request on 2026-11-14 16:58:24 UTC (2026-11-15 00:58:24 Beijing time). Its manifest is `interrupted`, with no active PID, and its last completed checkpoint is day 12. All records, including subsequent day-13 activity, remain preserved. The stop receipt is `stop-request-20261115.json`. The old model supervisor then exited through its existing automatic lifecycle; start the model service before the new institute's preflight. The previous source was `1c60e9784c3c53fd98cda3029a6ed3fa202ee311`, and its retained CUDA image is `sha256:3773049a0729b148e2c6a5a9f84a908c3d5ff0f93ceb978bcfc157728c1ae631`. Earlier startup and CUDA acceptance details remain in the [2026-11-14 project log](../../docs/logbook/PROJECT_LOG_2026-11-14).

The replacement two-A100 instance is `3zz5jox6oiy7cojg5fk93adr9` (`di-20261115133357-w2hbx`), with SSH `root@115.190.90.101:64295`. The original instance `8sm69kjapr5m8teum8myfhz80` stopped on November 15 at 13:20 Beijing; the platform did not match a platform stop command and reported its cause as unknown. The Zenith personal API is `https://zenith.bza.edu.cn/pt/api2`; `/instances/{instanceId}/ssh-access` and `/me/ssh-keys` expose access metadata. Registered key synchronization uses POST `{}` to `/instances/{instanceId}/inject-ssh-keys`, followed by its returned status URL and a real SSH probe. Keep host-key verification enabled and platform credentials outside the researcher environment. On the replacement host, platform key injection reported success but the vendor rewrote `/root/.ssh/authorized_keys`. After explicit user approval, the existing `lty-zenith` public key was placed in `/root/.ssh/authorized_keys2`, which the unchanged SSH configuration already supports. Actual login on port 64295 was then verified. Never copy a private key into the guest or treat an injection receipt as proof of working SSH.

The historical two-arm deployment remains at `/project_c20250210/260903018/socio-evo-autoresearch/deployment-20261113`, with source `0770bc3`, image `socio-evo-autoresearch:ebf4bb5` and seed `20260302`. Both arms completed day 28 before the stop request; no termination or deletion was necessary. Its viewer remains separate on port 8919. See the [original protocol plan](../../docs/plans/2026-11-13-autoresearch-town-academy.md), [deployment history](../../docs/logbook/PROJECT_LOG_2026-11-13) and [completion record](../../docs/logbook/PROJECT_LOG_2026-11-14). The earlier 14-day local-model pilot remains in the [pilot archive](../../docs/archive/research-pilot.md).
