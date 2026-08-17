"""Instagram bot CLI contract — mahogany.cli requires main()."""

from mahogany.jobs import instagram_bot


def test_instagram_bot_exposes_main_for_cli():
    assert callable(getattr(instagram_bot, "main", None))
    assert callable(getattr(instagram_bot, "run", None))


def test_instagram_rotation_is_lifestyle_first():
    tips = sum(1 for t in instagram_bot.ROTATION if t == "tip")
    listings = sum(1 for t in instagram_bot.ROTATION if t in {"listing", "rental"})
    assert tips >= listings
    assert "tip" in instagram_bot.ROTATION
    assert "community life" in instagram_bot.MAYA_IG_SYSTEM.lower() or "lake" in instagram_bot.MAYA_IG_SYSTEM.lower()
