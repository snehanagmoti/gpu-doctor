# JSON output

`gpu-doctor --json` prints a single JSON object. Its formal definition is
[json-schema.json](json-schema.json) (JSON Schema 2020-12). The test suite
validates real output from several fake machines against that file, so the
schema and the program cannot drift apart.

## Stability promise

* `schema_version` is `1`. It is increased only for an incompatible change:
  removing or renaming a key, or changing a value's type or meaning.
* New keys may be added at any time. Consumers should ignore keys they do not
  know.
* Check `id`s are stable. A check may be added; an id is never reused for a
  different check.
* `facts` keys are per check and may grow over time.

## Top level

| Key | Type | Meaning |
|---|---|---|
| `schema_version` | integer | always `1` for this format |
| `tool` | object | `{"name": "gpu-doctor", "version": "0.1.0"}` |
| `overall_status` | string | worst status: `pass`, `warn` or `fail` (`skip` counts as `pass`) |
| `exit_code` | integer | the process exit code, 0–3 |
| `checks` | array | one object per check, in run order |

## Each check

| Key | Type | Meaning |
|---|---|---|
| `id` | string | stable identifier, e.g. `secure_boot` |
| `title` | string | human-readable name |
| `status` | string | `pass`, `warn`, `fail` or `skip` |
| `summary` | string | one line |
| `explanation` | string | plain-language reason; may be empty |
| `fixes` | array of strings | shell commands the user may run; never run by gpu-doctor |
| `evidence` | array of `{source, value}` | what was read and what it contained |
| `facts` | object of strings | machine-friendly values, e.g. `driver_version`, `module_source`, `secure_boot` |
| `internal_error` | boolean | the check crashed; this is a gpu-doctor bug and makes the exit code 3 |

## Examples

Failed check ids:

```sh
gpu-doctor --json | jq -r '.checks[] | select(.status == "fail") | .id'
```

The running driver version, if known:

```sh
gpu-doctor --json --check kernel_module | jq -r '.checks[] | select(.id == "kernel_module") | .facts.kernel_module_version'
```
