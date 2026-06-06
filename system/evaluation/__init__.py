"""Shared evaluation protocol, metric, and runtime helpers.

Import concrete helpers from their submodules so lightweight consumers such as
backend path configuration do not eagerly load Torch or scikit-image.
"""
