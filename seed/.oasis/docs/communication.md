# Work connections

Cameleer assigns a short goal and the context needed to act to a visible Camel.
Use the actual chat ID for links and follow-up; `camel_A_goal` is an optional title
convention. Give the goal, work location and relevant context in a concise message.

Keep `.oasis/state/tasks.md` concise: chat ID/link, goal, stage and dependency,
work location/result reference, and final result/check summary. Cameleer updates
it while assigning, collecting or resuming. Read active work and the relevant
entry rather than repeatedly collecting every chat's status.

Read the applicable skill experience before choosing an approach. Once before
the final completion report, consolidate useful lessons in the existing owner
under [knowledge policy](../manual/knowledge.md).

Camel sends a short completion message directly to Cameleer, for example:

> Completed. Main change: … / Related checks: …
> Result: …
> Please review, integrate and archive this work.

Cameleer checks the request, diff and reported checks, integrates completed work,
and adds checks only for effects introduced by integration or doubtful evidence.
After collection it retains the result link and archives Camel automatically.
Later corrections restore the same chat. Unfinished work stays available there.
Repeated completion delivery must not cause repeated integration.

Intermediate messages to Cameleer are useful for a material goal/scope change or
a problem Camel cannot resolve. Keep routine progress local. For Camel-to-Camel
dependencies, use the [one terminal notice](../../LocalGitWorkflow.md#dependency-waiting-and-resumption)
after the named portion completes, fails or is cancelled. Keep independent
work moving and resume from that result.

Planning uses [actual native Plan mode](../../ProjectGuide.md#planning-work) and
starts from the supplied request. Unsupported mode-setting paths give one manual
mode-and-start instruction. Existing model, reasoning, permissions and project
settings carry into role chats through supported native interfaces.

Use compact English for internal work context, preserve exact localized literals,
and speak to the user in their language. A narrow result/reference usually gives
the next worker enough context without a transcript. Reconcile uncertain create,
send, integration or archive operations before repeating that operation.
