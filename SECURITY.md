# Security

FuelCell-RAG is a portfolio project. All data is public or synthetic and no personal data is
processed.

If you find a vulnerability, please open a private security advisory on GitHub
(Security → Report a vulnerability) rather than a public issue. Expect a reply within a week.

What the project already does: a secret scan (gitleaks) and a dependency audit (pip-audit) run on
every pull request, accepted audit findings are listed with reasons in
`.github/pip-audit-ignore.txt`, the API can require a key (`FCRAG_API_KEY`), and answers are
tested against prompt injection planted in documents (see the README, Evaluation).
