# Project log — 2026-10-21

## Clear invitation and Rest outcomes

Expired appointments now say the invitation was not sent and show the requested appointment time alongside the execution clock; expired Rest requests likewise show their requested ending time and current time, including day and seconds. Immediate invitations keep the existing null/now input and bind to execution time. One Work-selection sentence clarifies that residents can enter Work before claiming a job.

Activity tool completion returns the operation outcome to realtime instead of losing a caught rejection and emitting a successful-looking finished message. Rejections carry success:false and their reason; successful invitation operations return a real stored identifier, with created distinguishing a new invitation from an already-existing one. Ordinary tool completion remains neutral, so finishing a test command does not imply its tests passed. The frontend displays explicit failures, real invitation creation and neutral ended for legacy events without outcome data. The resident receives the same underlying rejection reason, with no new invitation or identifier on failure.

The combined local infrastructure, agent, interaction, activities, realtime, scheduler/activity-clock and community-config selection passed 612 tests in 49.02 seconds. New integration tests use an actual resident decision that crosses an appointment time, verify the immediate path binds to execution time and exposes its stored identifier, check expired Rest day/time feedback, and distinguish duplicate invitations. Eight old Rest cases were updated from the old error phrase while retaining all state assertions. Independent focused review, existing frontend timeline/activity/conversation checks, Ruff lint/format and git diff --check passed. The change adds no invitation mode, automatic retry or general status framework. Delivery validates a complete Linux candidate before updating the future default and publishes only the changed frontend event-renderer asset; the frozen current experiment and all services remain untouched.

## Partner availability and invitation reply delivery

The board now lists current job holders and briefly suggests approaching residents without a job when choosing a team partner. It uses the board's active claims, so completed jobs do not leave residents incorrectly marked as occupied; this remains guidance rather than a new claiming restriction.

Invitation replies wake a sender resting with invitation wakeups enabled, including Rest waiting for that specific invitation; rescheduling matches its supersedes reference and unrelated replies do not wake a targeted wait. Existing incoming-invitation wakeups remain intact. During another Activity, the sender's automatic notification is queued until actual Activity exit and hidden from automatic invitation views and menus meanwhile; explicit help/status queries can still read the actual state. The small queue survives checkpoints. Delivery uses the current clock with a reference to the original event, occurs after a direct transition into Rest, and can immediately wake that Rest without repeating invitation side effects.

The final combined local selection passed 621 tests in 49.95 seconds. Focused coverage includes accept/decline/defer, busy tool observations, checkpoint restoration, direct Work-to-Rest delivery, relevant versus unrelated replies, disabled wakeups, incoming invitations and the current claim roster. All three existing frontend checks, modified Python lint/format and git diff --check passed. The supplement changes no frontend asset beyond the preceding event-renderer change, launches no experiment and requires no service restart.

## Planning detail ending and next activity

Planning details no longer repeat the departure sentence in both Status and Activity log: ended Planning uses a neutral status and keeps the recorded departure once. A Next activity field now shows the same resident's actual immediately succeeding Activity entry and available venue. The replay cutoff still applies; a rejected, cancelled or missing entry is not presented as a successful selection, and a movement origin is not mislabeled as its destination.

The existing frontend timeline check now covers the model boundaries and the actual person-details DOM, including a single departure sentence, Work at Workshop, rewind visibility and missing-entry behavior. All three existing frontend checks and git diff --check passed. This is a replay/rendering change only; backend regression remains the preceding local 621 and Linux 621 passing tests.

## Zenith delivery

Published code 268c959b7df2e172ac507e7345c55cbc472d2443 as the future default at 00:29:59 Asia/Shanghai. Its backend is unchanged from the independently reviewed cffce9c candidate, which passed the same 621-test Linux selection in 64.67 seconds. Final frontend timeline/activity/conversation checks passed on Linux Node 16 using scratch-only test compatibility helpers for structuredClone/findLast; all three changed production scripts passed native syntax checks. The activity model, person-details renderer and tool-event renderer were backed up and published under the existing lock, with matching candidate/source/published/HTTP hashes and no-store headers.

The current v2 experiment remains running from frozen d34b514, with its process identity unchanged; model, gateway and viewer services were not restarted. Old experiment result hashes remain unchanged. No model requests or experiment start/stop actions were performed. Local delivery evidence is /private/tmp/socio-invitation-feedback-20261020/receipt.json, with Linux and deployment logs alongside it. The frontend fixes are visible now; backend behavior applies when starting from the new default.

## Correct duplicated Planning card feedback

The user's Tomas day-2 screenshot showed that the new Next activity field was already present, but the departure sentence still appeared both in the decision card's feedback and in the independent Activity log. The earlier DOM fixture had omitted the decision itself and therefore missed this path; a cache explanation did not account for the screenshot.

The person-details renderer now excludes its independently displayed ending event from the same-time events passed into the decision card. The shared card renderer, original departure log and Next activity field remain unchanged. The corrected DOM regression includes a real-shaped select_rest decision with thought and a same-time departure: before the fix it fails with two copies rather than one, and after the fix it passes. Further checks retain rejection and ordinary tool feedback inside decision cards. All three existing frontend checks and git diff --check passed; this one-asset correction changes no backend or experiment state.

The corrected card renderer was deployed as code 906ca17f65db8327a42370eae88a1f9ea454d2de at 00:50:05 Asia/Shanghai. The three Linux frontend checks passed, and its single changed asset passed native Node 16 syntax validation. Candidate, viewer source, published file, remote HTTP and local port-8765 tunnel HTTP all match SHA-256 c05d35f3a8df7e0d2e389be39cde13988dbfc6188801d60c6ae6dde41705fa36, with no-store headers. The future default now points to this complete snapshot. The running frozen d34b514 experiment, services, other assets and old results remain unchanged. Evidence is in /private/tmp/socio-planning-card-dedup-20261021/.

## Concrete Planning outcome text

Mei's reported day-2 membership beginning at event 4418 ends with a resume_work decision at 4431, departure at 4432 and actual Work entry at 4433. The previous display reduced that successful choice to Work at Workshop and retained the generic departure sentence. A shared summary now describes the actual next entry and, when the directly matching successful decision is available, its concrete operation: this example becomes Resume Work at Workshop in both the Next activity field and the departure sentence. Rest deadlines, recorded conversation peers and movement destinations use available matching data; internal activity identifiers are used for association rather than prominent text.

The summary requires a real successor within the replay cutoff and does not borrow a rejected choice. The departure is still rendered once, and the stored experiment events remain unchanged. The frontend timeline check covers the reported 4418/4431/4432/4433 event shape in the rendered DOM, matching field/end text, absent or future entries, refused choices, Rest and Move summaries. This is a frontend-only correction for existing experiments.

All three existing local frontend checks and git diff --check passed. The shared-summary import was checked for cycles; backend behavior and the preceding 621-test Linux result are unaffected.
