# Sprint: Video Production Capability — OpenMontage Integration

## Architecture

```
User
  ↓
LibreChat
  ↓
GoalOS Agent
  ↓
VIDEO_PRODUCTION capability
  ↓
OpenMontage adapter (subprocess-based)
  ↓
OpenMontage pipeline (12 pipelines, 100+ tools)
  ↓
Tools / Providers (Pexels, Pixabay, fal.ai, etc.)
  ↓
Render → Quality Check → Video Artifact
  ↓
GoalOS artifact store
  ↓
User / Future Social Publishing
```

## Key Design Decisions

1. **OpenMontage is agent-first, not REST API.** GoalOS invokes it as a controlled subprocess with project directories.
2. **Pipeline state machine**: idea → script → scene_plan → assets → edit → compose → publish
3. **GoalOS owns orchestration**, OpenMontage owns video production.
4. **Provider-neutral**: GoalOS doesn't know which AI model generates the video — OpenMontage handles provider selection.

## Files Changed

### New Files

| File | Purpose |
|---|---|
| `app/db/models/video_production.py` | Video production job model with pipeline states |
| `app/schemas/video_production.py` | Request/response schemas for video API |
| `app/integrations/video/__init__.py` | Video integration package |
| `app/integrations/video/openmontage_adapter.py` | OpenMontage adapter — subprocess bridge |
| `app/services/video_service.py` | Video production service — lifecycle management |
| `app/api/v1/video_production.py` | REST API endpoints for video production |
| `integrations_manager/app/providers/openmontage.py` | OpenMontage Integrations Manager provider |
| `tests/test_video_production.py` | 39 comprehensive tests |
| `docs/sprint_video_production.md` | This documentation |

### Modified Files

| File | Change |
|---|---|
| `app/api/router.py` | Registered video production API |
| `app/db/models/__init__.py` | Added VideoProduction, VideoJobStatus |
| `app/agents/capability_definitions.py` | Added 6 video capabilities |
| `integrations_manager/app/providers/__init__.py` | Registered OpenMontage provider |
| `integrations_manager/tests/test_providers.py` | Added OpenMontage provider tests |
| `integrations_manager/README.md` | Updated supported integrations table |
| `integrations_manager/env.example.txt` | Added OpenMontage env vars |
| `goalos.env.example` | Added OpenMontage configuration section |

## API Endpoints

| Method | Path | Description |
|---|---|---|
| GET | `/api/v1/video/pipelines` | List available video pipelines |
| GET | `/api/v1/video/status` | OpenMontage provider configuration status |
| POST | `/api/v1/video` | Create a video production job |
| GET | `/api/v1/video` | List video production jobs |
| GET | `/api/v1/video/{job_id}` | Get a specific video job |
| POST | `/api/v1/video/{job_id}/start` | Start production on an approved job |
| POST | `/api/v1/video/{job_id}/approve` | Approve a job awaiting approval |
| POST | `/api/v1/video/{job_id}/cancel` | Cancel a running/queued job |
| POST | `/api/v1/video/{job_id}/retry` | Retry a failed job |
| GET | `/api/v1/video/{job_id}/poll` | Poll current job status |

## Job Lifecycle

```
QUEUED → PLANNING → AWAITING_APPROVAL → GENERATING → RENDERING → REVIEWING → COMPLETED
                                                                 ↘ FAILED
QUEUED → CANCELLED
FAILED → QUEUED (retry)
```

## Pipelines Available

| GoalOS Pipeline | OpenMontage Pipeline | Description |
|---|---|---|
| auto | (auto-select) | Best pipeline for the request |
| explainer | animated-explainer | AI-generated animated explainer |
| talking-head | talking-head | Presenter-led video with footage |
| cinematic | cinematic | Cinematic edit with footage and music |
| clip-factory | clip-factory | Extract short-form clips |
| podcast-clip | podcast-repurpose | Turn podcast into video |
| animation | animation | Full animation production |
| character-animation | character-animation | Character-driven animation |
| hybrid | hybrid | Source + AI hybrid |
| avatar | avatar-spokesperson | AI avatar presenter |
| localization | localization-dub | Localize and dub video |
| screen-demo | screen-demo | Screen recording with narration |

## Capabilities Registered

| Capability | Description | Requires Approval |
|---|---|---|
| `video_create_project` | Create a video production project | Yes |
| `video_start_production` | Start production on approved job | Yes |
| `video_get_status` | Get job status and progress | No |
| `video_list_pipelines` | List available pipelines | No |
| `video_cancel` | Cancel a running job | Yes |
| `video_retry` | Retry a failed job | Yes |

## Environment Variables

```bash
# Path to the OpenMontage installation directory
GOALOS_OPENMONTAGE_PATH=/opt/OpenMontage

# Directory where OpenMontage stores projects and outputs
GOALOS_OPENMONTAGE_PROJECTS=/opt/openmontage-projects

# Default pipeline when auto-selecting
GOALOS_OPENMONTAGE_DEFAULT_PIPELINE=animated-explainer

# Maximum time (seconds) for a single production run
GOALOS_OPENMONTAGE_TIMEOUT=1800
```

## Cost Governance

Video production is declared as HIGH risk in the Action Policy:
- Always requires approval before starting
- Cost estimate tracked per job
- Actual cost tracked after completion
- No silent spending through paid providers

## Security

- OpenMontage credentials never exposed via API
- Project paths validated against traversal
- Subprocess execution uses controlled command construction
- Output validated with ffprobe before marking completed
- Failed jobs cleaned up safely

## What Is Working Now

- ✅ Video production job model and database
- ✅ OpenMontage adapter (subprocess bridge)
- ✅ Pipeline mapping (12 pipelines)
- ✅ Job lifecycle (create, start, approve, cancel, retry, poll)
- ✅ Output artifact validation (ffprobe)
- ✅ REST API for video production
- ✅ 6 GoalOS capabilities registered
- ✅ Integrations Manager provider
- ✅ Action Policy (HIGH risk, approval required)
- ✅ 39 tests passing
- ✅ Zero regressions (1554 total tests pass)

## What Requires KVM Setup

1. Clone OpenMontage: `git clone https://github.com/calesthio/OpenMontage.git /opt/OpenMontage`
2. Install: `cd /opt/OpenMontage && make setup`
3. Configure: `GOALOS_OPENMONTAGE_PATH=/opt/OpenMontage`
4. Optionally add API keys for paid providers (fal.ai, Pexels, etc.)

## What Remains for Full End-to-End

1. **OpenMontage installed on KVM** — currently not installed
2. **Agent-driven execution** — OpenMontage expects an AI agent to drive its pipelines; GoalOS needs to either invoke its tool registry directly or delegate to an LLM agent
3. **Remotion composer** — Node.js-based final composition (installed by `make setup`)
4. **Asset generation** — depends on configured providers (Pexels/Pixabay are free)
5. **Social publishing** — video output → Meta/LinkedIn/X (future sprint)

## External API Keys (Optional)

| Provider | Purpose | Required? |
|---|---|---|
| Pexels | Free stock footage | Optional (free) |
| Pixabay | Free stock footage | Optional (free) |
| fal.ai | AI image/video generation | Optional (paid) |
| ElevenLabs | Premium TTS | Optional (paid) |
| Suno | Music generation | Optional (paid) |

OpenMontage can operate with free/local tools only (Piper TTS, Pexels, Pixabay).
