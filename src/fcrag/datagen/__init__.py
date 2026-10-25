"""Synthetic corpus generators: turn the system YAML truths into engineering documents.

Every generator also records where it states each truth value (a *fact*: page, sheet and cells,
or requirement ID). The evaluation harness uses those facts as gold sources, so retrieval and
citation metrics need no hand labelling.
"""
