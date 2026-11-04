# Provisional schema for AI Build Kit to own once published

This folder holds a draft for AI Build Kit to adopt. It is not a published
upstream schema. Ownership and versioning are defined in the
[contract guide](../README.md).

`upstream.json` is the reviewed origin pin. Its value is `null` until a
published schema is adopted. With an empty or absent pin, the vendoring check
reports "could not check" and exits `2`.

To adopt a published copy, replace `null` with an object containing exactly:

| Field | Content |
|---|---|
| `repository` | `https://github.com/gwpicard/ai-build-kit.git`, the only allowed repository. |
| `tag` | The upstream release tag, without `refs/tags/`. |
| `commit` | The full, lowercase 40-character commit ID to which the tag resolves. |
| `path` | The schema's repository-relative path at that commit. |
| `sha256` | The lowercase SHA-256 of the published file's exact bytes. |

Save the pin and the unchanged published schema together for review. The
check reads the pin from `HEAD` and requires the working copy to match it.
Adoption needs only the pin and vendored file to change when the published
schema matches this contract. A changed contract may also require validator
and fixture updates.

The check fetches the named tag from AI Build Kit into a temporary repository,
resolves annotated or lightweight tags to a commit, checks the commit and
file hash, then compares bytes. Fetch or confirmation failures return `2`;
a confirmed upstream file that differs from the vendored copy returns `1`.
A local path cannot be used as the pin's repository. Tests substitute local
transport through an internal Python argument that the command cannot accept.
