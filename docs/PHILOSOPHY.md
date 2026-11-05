# Why AI Host Kit exists

AI Host Kit shares [AI Build Kit's philosophy](https://github.com/gwpicard/ai-build-kit/blob/docs/philosophy-reach/docs/PHILOSOPHY.md):
help people who do not write code own and maintain useful software, in accounts
they or their organisation control. A person should be able to understand what
will happen, approve it and check the result without reading code.

AI Build Kit owns what the tool is: its code, tests, requirements and records.
AI Host Kit owns where and how it runs, including recovery and access to the
hosting environment. They talk only through `handover.json`, written by the
build kit, `host-record.json`, written by the host kit through a pull request
the person merges, and four requests: a preview, recent logs, a health check
and a release. Neither kit edits the other's files or restates its rules.

Hosting work runs from the person's computer. Backups, monitoring and other
unattended work belong to machinery in the person's environment. AI Host Kit
runs no service of its own. A valid handover and a container should be enough
to use it without AI Build Kit.

Each instruction needs a mechanism, measured evidence that it helps, or a
judgement a machine cannot make. Shell checks guard boundaries; conversation
replays will measure behaviour when there is behaviour to test. A host recipe
needs a recorded real run before it is offered as proven.

The kit is beta. Local host choice and saved-plan approval tools are built; no host is proven.
[PROMISES.md](PROMISES.md) records the missing mechanisms; an intention is not
a guarantee.
