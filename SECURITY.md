# Security policy

Please do not report security issues in a public issue or Discussion.

If the issue is safe to disclose, open a minimal issue without credentials, private memory values, production URLs with
tokens, or raw logs. For a potentially exploitable issue, do not post details publicly; use GitHub's private vulnerability
reporting channel if it is enabled, or contact the repository maintainers privately through GitHub.

The implementation security guide is in [docs/security.md](docs/security.md). Never commit API keys, database URLs,
runtime tokens, private memory exports, or customer data.

## What the package sends and stores

- **Sent to Bilinc Cloud, over HTTPS:** the API key (in a request header) and the memory keys, values, reasons and options of each call. The SDK refuses a non-`https://` base URL except for `localhost`, `127.0.0.1` and `::1`.
- **Stored on this computer:** only what `bilinc login` saves (API key and its host, in a file readable only by you) and the files you ask `bilinc wiki` or `export_wiki` to write. There is no local memory database in this package.
- **Deleting:** `forget` removes a memory from recall; `forget --purge` also removes its stored content from history and snapshots. Retention on Bilinc Cloud is described in the [privacy policy](https://bilinc.space/privacy).

