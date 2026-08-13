# Limitations

Radar Bench is deliberately narrow. Its evidence should not be generalized
beyond the tested boundary.

- **Small N:** five historical cases and twenty safety twins are not a
  population sample or confidence interval.
- **Python/pandas concentration:** the historical cases are heavily concentrated
  in the Python ecosystem and include several pandas incidents.
- **Limited cross-repository cases:** one cross-repository requirement cannot
  represent the wider dependency graph or maintainer ecosystem.
- **Constructed safety set:** the twenty safety twins are useful for boundary and
  abstention checks but are not naturally occurring incidents.
- **Public-gold memorization risk:** evaluator material is separately distributed
  for reproducibility, so a public candidate can memorize known gold.
- **No hidden tests:** this is a public, inspectable benchmark contract; passing
  it does not establish performance on undisclosed cases.
- **Platform/ecosystem limits:** canonical execution targets Linux/x86-64 Docker,
  and results may not generalize to other operating systems, architectures,
  package managers, resolvers, or dependency ecosystems.
- **Historical input availability:** wheelhouses and upstream records can become
  unavailable. A blocked case remains blocked and is not replaced.
- **Security boundary:** Docker controls are defense in depth, not a guarantee of
  multi-tenant isolation. Run on disposable infrastructure.

The frozen negative product result also means Radar does not ship an automatic
attribution agent, repair agent, GitHub integration, or production inference
service.
