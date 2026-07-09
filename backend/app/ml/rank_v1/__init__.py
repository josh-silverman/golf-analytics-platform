"""Rank-native model research track (rank_v1).

Isolated from the production ``golf_v1`` model: this subpackage reuses the
existing feature extraction, catalog, and backtest primitives unmodified and
registers under its own registry namespace. See
``docs/rank-native-model-design.md``.

Currently contains the **evaluation harness only** (``evaluation``). No model,
trainer, or serving code exists yet — the harness is built and validated in
isolation first, so the measurement tooling is proven correct before any
rank-native model is written on top of it.
"""
