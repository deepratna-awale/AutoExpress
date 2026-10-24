# Security policy

## Supported versions

Security fixes go into the latest release and the `main` branch.

## Reporting a vulnerability

Please don't open a public issue for security problems. Report them privately through [GitHub's private vulnerability reporting](https://github.com/deepratna-awale/AutoExpress/security/advisories/new), and include:

- what the problem is and where it is (file, route or setting),
- steps to reproduce it, or a proof of concept,
- the impact you expect.

You should get a reply within a week. Once a fix is released, the advisory is published with credit to you, unless you'd rather stay anonymous.

## Scope

The standalone app is a local tool. It has no user accounts, and it's meant to run on your own machine or a private network. Reports about these are the most useful:

- path traversal or file access outside the output folder,
- ways to run commands or code through the HTTP API,
- API keys (Civitai, WebUI logins) leaking into logs, responses or saved images.

Exposing the app to the public internet without a reverse proxy and authentication is not supported.
