# AI Business Operator: test matrix (what is proven, by what, and what is not)

Doubles used everywhere: Google is the in-memory `V2Google`; the AI is a scripted stand-in. Database, row-level security, policy, executor, gate and routes are real.

| Claim | Proven by | Level |
|---|---|---|
| A weak description gets a complete AI-drafted replacement stored for approval, with before and after, and Google is not touched | `test_prepare_drafts_the_complete_description...`, browser check "stored change shows BEFORE and AFTER" and "wrote NOTHING to Google" | real server logic, scripted AI |
| Preparing twice opens the same change and pays for one draft | `test_preparing_again...`, browser | same |
| AI down (no credit, bad key, busy) is told in words; nothing invented | `test_when_the_ai_is_down...`, `test_the_ai_being_down...`, browser | same |
| Only the owner can answer attributes, holiday hours, service area | `test_areas_only_the_owner_knows...` | same |
| One pending list from `agent_actions`, replies, posts, tasks, no copy; categories and counts | `test_the_pending_list...`, `test_replies_and_posts_appear...` | same |
| A change the Google gate holds shows no Approve and says why; on a dedicated test profile it can be approved | `test_a_drafted_change_on_a_closed_gate...`, `test_on_a_dedicated_test_profile...`, browser | gate logic real, Google a double |
| Edit and regenerate replace the proposal, never leave two live, and a failed AI draft keeps the old one | `test_editing...`, `test_regenerating...` | same |
| The registry has no approve/publish/write tool; made-up tools, extra arguments, low roles are refused | `test_the_registry_has_no_tool...`, `test_a_made_up_tool...` | real |
| A location or review id from the model cannot reach another business | `test_a_location_id_from_the_model...`, `test_the_operator_cannot_draft_a_reply_to_someone_elses_review` | RLS real |
| Instructions hidden in a review cannot approve or publish; phones are redacted; review text is withheld when policy says | `test_instructions_hidden...`, `test_phone_numbers...`, `test_review_wording_is_withheld...` | real |
| The model's claim is shown as its claim; the stored proposal is what the card shows | `test_the_final_answer_never_becomes_the_change...` | real |
| Malformed turns: one repair then stop; both-tool-and-answer refused; loop bounded at 6 | three orchestrator tests | real |
| The operator drafts a reply or a post that waits for approval and publishes nothing | `test_the_operator_drafts_...` (2) | real |
| Staff can read but not prepare or ask | `test_staff_can_read_the_list...` | real |
| Checklist rows open the prepared change, not the generic editor | `test_checklist_rows...`, browser | real |
| Approving writes once and counts as applied only after the profile is read back | browser run (approve: `update_calls` 1, row `executed` with `verified_at`), existing executor suite | executor real, Google a double |
| Profile areas have real controls; no dead chip; phone has no sideways scroll and no tiny targets | browser, 26 checks, desktop and 390px phone | real browser |

## Not proven, stated plainly

* **Any real Google write.** Nothing here ran against Google. The live test is `AI_OPERATOR_LIVE_TEST_RUNBOOK.md`, not run.
* **How a real model behaves.** The AI is scripted. Quality, safety-rule refusals and the JSON-format reliability of `gpt-4o-mini` are unmeasured. The production key was found expired (401) on 2026-11-25.
* **Native tool calling** (see architecture doc): documentation only, not live-verified, not wired.
* **Campaign (Marketing Studio) posts** appear in the list because they are `scheduled_posts` awaiting approval; no campaign-specific test was added.
* **Services, categories, attributes, service area** have no AI "prepare" of their own beyond what the existing V2 scan produces; the screen says so when nothing can be prepared.
* **Edit and regenerate** exist for the description only.
* **No audit page for operator conversations**: runs are recorded as `operator.ask` audit rows (tools used, changes prepared), not as chat transcripts.
