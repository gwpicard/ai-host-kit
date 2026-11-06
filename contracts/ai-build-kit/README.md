# Published AI Build Kit handover schema

AI Build Kit owns this published schema. AI Host Kit vendors it unchanged at
`handover.schema.json`. The [contract guide](../README.md) describes its use.

`upstream.json` pins the origin with exactly these fields:

| Field | Content |
|---|---|
| `repository` | `https://github.com/gwpicard/ai-build-kit.git`, the only allowed repository. |
| `ref` | The upstream branch the commit must be reachable from, without `refs/heads/`. |
| `commit` | The full, lower-case 40-character commit ID. |
| `path` | The file's repository-relative path at that commit. |
| `blob` | The full, lower-case 40-character Git blob ID. |
| `sha256` | The lower-case SHA-256 of the file's exact bytes. |

The check reads the pin from `HEAD` and requires the working copy to match it.
It fetches the commit and named branch into a temporary repository, confirms
reachability, blob ID and SHA-256, then compares the vendored bytes. It does
not need a release tag. Fetch or confirmation failures return `2`, "could not
check". Confirmed upstream bytes differing from the vendored copy return `1`.

The command accepts no pin, file or transport overrides. Tests replace only
the transport through an internal Python argument; a local repository cannot
be named in the pin. Save an adopted pin and unchanged schema together.
