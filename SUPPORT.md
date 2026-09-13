# Getting help

- **A page extracted wrongly?** Open an
  [extraction quality report](https://github.com/BeastxD7/webgraph/issues/new?template=extraction_quality.yml)
  with the URL. This is the most useful thing you can send us.
- **Something crashed or errored?** Open a
  [bug report](https://github.com/BeastxD7/webgraph/issues/new?template=bug_report.yml).
- **How does X work?** Start with `README.md` (the pipeline, stage by stage), `docs/` (session
  records with the measurements behind each decision) and `MEMORY.md` (the engineering
  journal). Then ask in
  [Discussions](https://github.com/BeastxD7/webgraph/discussions).
- **Security problem?** See [`SECURITY.md`](SECURITY.md) — please do not open a public issue.

Include the commit you are running (`git rev-parse --short HEAD`) and, for extraction
questions, the run log copied from the web UI: it carries every decision the engine made
for that page.
