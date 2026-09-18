"""Fixture-based evaluation of generation and grading.

The harness ingests a short source in a known language, generates and publishes a tutorial from
it, then answers the generated questions as a synthetic student and compares the grades and
routes with what the fixture says to expect. Nothing here is a unit test: the point is to run the
same inputs through whatever providers are configured, so two model choices can be compared.
"""
