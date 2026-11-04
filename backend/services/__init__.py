"""
Services package for Onigiri.
"""


def seed_data(*args, **kwargs):
    from services.seed import seed_data as _seed_data
    return _seed_data(*args, **kwargs)


__all__ = ["seed_data"]
