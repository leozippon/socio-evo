"""The agent runtime: a persistent tool-calling session over the resident's own directory.

The runtime knows nothing about the town. It meets the world through `agent.port`, declares the
world's tools alongside its own file tools, forwards calls, appends results, compacts its context
when it grows long and traces everything it does.
"""
