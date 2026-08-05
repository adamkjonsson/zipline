# About Zipline payload format

This projects specifies a file format for decoded payload data from network traffic.

The format is currently specified in docs/zipline-payload-format.md.

The aims of the format is also described there.

The specification must be written in a clear and succinct way so that it is easy to understand for those who will implement language support for it.

## Python

Every Python file must produce **zero warnings** from `ruff check`, and must be
formatted the way `ruff format` formats it. Both are configured in `ruff.toml`;
`requirements.txt` pins the version.

```
ruff check .     # must report "All checks passed!"
ruff format .    # must report nothing left to reformat
```

Silencing a warning is a decision, not a workaround: prefer fixing the code, and
where a rule genuinely does not fit, add a `per-file-ignores` entry to
`ruff.toml` with a comment saying why. Do not scatter `# noqa`.

The vector suite itself uses **only the standard library**, deliberately —
regenerating or verifying the vectors must not depend on anything being
installed. `requirements.txt` is for the linter alone.
