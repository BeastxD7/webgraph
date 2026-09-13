# Security policy

## Reporting a vulnerability

Please report security problems privately through
[GitHub's private vulnerability reporting](https://github.com/BeastxD7/webgraph/security/advisories/new)
rather than a public issue. Include the affected component (engine, API, web app), a
reproduction, and the impact as you understand it. You will get an acknowledgement within
72 hours and a decision on severity and timeline within 7 days.

We ask for coordinated disclosure: give us a reasonable window to ship a fix before
publishing details. We will credit you in the release notes unless you prefer otherwise.

## What counts

webgraph fetches and renders arbitrary web pages on behalf of a caller, so the interesting
surface is the fetch path and the API around it:

- **Server-side request forgery.** The API refuses private, loopback and link-local
  addresses by default (`BlockedHostError`); a bypass of that check is a vulnerability.
- **Renderer escape.** Pages are rendered in Chromium through Playwright; anything that
  lets a page reach the host filesystem, other origins' data, or the API process.
- **Resource exhaustion by a hostile page** beyond the configured limits (page size, render
  timeout, crawl caps) — a page that hangs or exhausts a worker is a bug we want to hear
  about, though ordinary rate limiting is the deployer's responsibility.
- **Injection through extracted content**: Markdown or facts that, when rendered by the web
  app, execute script or load remote resources.
- **Secrets in traces or logs.** Run traces and run logs are meant to carry no cookies,
  credentials or tokens; if one does, report it.

Out of scope: the content of third-party sites, denial of service against the sites being
crawled (the crawler honours its own concurrency and page limits; misuse is on the operator),
and issues in dependencies without a demonstrated impact through this code.

## Supported versions

The `main` branch. There are no maintained release lines yet; fixes land on `main` and are
noted in `CHANGELOG.md`.
