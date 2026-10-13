# Pioneer evaluation inputs

These scenarios are inputs for a later review, not performed model outcomes.

| Request/state | Useful behavior to evaluate |
|---|---|
| Build a requested utility in Pioneer | Direct implementation with relevant checks and result references |
| Investigate lost input with an uncertain cause | Investigate the consuming layer and report evidence; a patch depends on the finding |
| Explain a project mode | Explain without changing the stored selection |
| Project grew with no mode-switch request | Retain Pioneer and its concrete task |
| Requested visible worker without a count | One Developer chat with a concise assignment |
| Requested two subagents for edits/checks | Use the requested workers and retain integration context |
| Planning request with native mode support | Set actual Plan mode and start the supplied planning task immediately |
| Planning request without a mode setter | Give manual mode-and-start guidance once in this chat |
| Approve a plan without asking for implementation | Follow the user's planning-to-implementation instruction |
| Request fast work | Implement promptly, brief check and exact deferred verification |
| Switch to Oasis while unfinished work exists | Preserve context and unrelated chats while establishing the new primary roles |
| Native create/send reply is lost | Reconcile that operation without duplicating roles or work |
| Another chat resembles a worker by title | Use actual linked IDs for the requested transition |
